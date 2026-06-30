// SPDX-License-Identifier: Apache-2.0
//
// Literal IP address property predicates. The source tests use local macros such as
// `ip!("127.0.0.1").is_loopback()`: recognition captures the raw receiver, while
// desugar expands held macro_rules! and parses the literal address with the live
// macro/binding context available.

use std::net::{IpAddr, Ipv4Addr, Ipv6Addr};
use std::rc::Rc;
use std::str::FromStr;

use sugar_ir_symbolic::{eq, Term};
use syn::{Expr, ExprCall};

use crate::sugar::claim::{ExprSugarClaim, SugarRole};
use crate::sugar::factory::{IpAddrFloor, SugarBody, SugarBuildCtx, TermFloor};
use crate::sugar::int_literal::{ExactInt, IntKind};
use crate::sugar::source_fragment::SourceFragment;
use crate::{
    bool_const, const_int, literal_string_value, num, strip_refs_groups, token_key,
    AssertionFactKind, Desugared, Effect, Outcome, Sugar, SugarCtx, TemporalScope, Warrant,
    MAX_MACRO_EXPANSION_DEPTH,
};

pub(crate) const EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::term_before(
    "literal_ip_addr",
    &["const_path", "path", "call", "method"],
    recognize_term,
);

pub(crate) const CONSTRAINT_EXPR_SUGAR: ExprSugarClaim = ExprSugarClaim::with_ordering(
    "constraint_literal_ip_addr_property",
    SugarRole::Constraint,
    &["constraint_bool_expr"],
    recognize,
);

struct IpAddrPropertySugar {
    method: String,
    receiver: SugarBody<IpAddrFloor>,
    site: String,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum LiteralIp {
    Any(IpAddr),
    V4(Ipv4Addr),
    V6(Ipv6Addr),
}

enum IpAddrSource {
    Literal(LiteralIp),
    Runtime(String),
    Ipv4New {
        octets: Vec<SugarBody<TermFloor>>,
        boundary: String,
    },
    Ipv6New {
        segments: Vec<SugarBody<TermFloor>>,
        boundary: String,
    },
}

struct IpAddrLiteralSugar {
    source: IpAddrSource,
}

fn recognize_term(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    match strip_refs_groups(expr) {
        Expr::Call(call) => recognize_ip_constructor_term(call, fcx, token_key(expr)),
        Expr::Path(path) => resolve_ip_const_path(&path.path).map(|ip| {
            Box::new(IpAddrLiteralSugar {
                source: IpAddrSource::Literal(ip),
            }) as Box<dyn Sugar>
        }),
        _ => None,
    }
}

fn recognize_ip_constructor_term(
    call: &ExprCall,
    fcx: &SugarBuildCtx,
    boundary: String,
) -> Option<Box<dyn Sugar>> {
    let (ty, method) = call_path_type_and_method(call)?;
    match (ty.as_str(), method.as_str(), call.args.len()) {
        ("Ipv4Addr", "new", 4) => Some(Box::new(IpAddrLiteralSugar {
            source: IpAddrSource::Ipv4New {
                octets: call
                    .args
                    .iter()
                    .map(|arg| SugarBody::term(arg, fcx))
                    .collect(),
                boundary,
            },
        })),
        ("Ipv6Addr", "new", 8) => Some(Box::new(IpAddrLiteralSugar {
            source: IpAddrSource::Ipv6New {
                segments: call
                    .args
                    .iter()
                    .map(|arg| SugarBody::term(arg, fcx))
                    .collect(),
                boundary,
            },
        })),
        _ => None,
    }
}

fn recognize(frag: &SourceFragment, fcx: &SugarBuildCtx) -> Option<Box<dyn Sugar>> {
    let expr = frag.as_expr()?;
    let Expr::MethodCall(call) = strip_refs_groups(expr) else {
        return None;
    };
    let method = call.method.to_string();
    if !is_supported_property(&method) || !call.args.is_empty() || call.turbofish.is_some() {
        return None;
    }
    Some(Box::new(IpAddrPropertySugar {
        method,
        receiver: SugarBody::from_node(Box::new(IpAddrLiteralSugar {
            source: resolve_literal_ip(&call.receiver, fcx.scope(), 0)
                .map(IpAddrSource::Literal)
                .unwrap_or_else(|| IpAddrSource::Runtime(token_key(&call.receiver))),
        })),
        site: token_key(expr),
    }))
}

impl Sugar for IpAddrPropertySugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        let ip = match self.receiver.reduce(ctx) {
            Outcome::Complete(desugared) => {
                let Some(term) = desugared.into_term() else {
                    ip_addr_gap("receiver completed as non-term");
                };
                ip_from_term(&term).unwrap_or_else(|| {
                    ip_addr_gap("receiver did not dispatch to the IP address floor")
                })
            }
            Outcome::Incomplete(effect) => return Outcome::Incomplete(effect),
        };
        let Some(value) = eval_property(ip, &self.method) else {
            ip_addr_gap(&format!(
                "recognized IP property `{}` has no evaluator at `{}`",
                self.method, self.site
            ));
        };
        Outcome::Complete(Desugared::Constraints {
            atom: eq(bool_const(value), bool_const(true)),
            n: 1,
            kind: AssertionFactKind::Warranted,
            warrant: Warrant {
                name: Some(format!(
                    "{}::ip-addr-property::{}",
                    ctx.scope.local_scope(),
                    compact_warrant_fragment(&self.site)
                )),
            },
        })
    }
}

impl Sugar for IpAddrLiteralSugar {
    fn desugar(&self, ctx: &SugarCtx) -> Outcome {
        match &self.source {
            IpAddrSource::Literal(ip) => Outcome::Complete(Desugared::Term(ip_term(*ip))),
            IpAddrSource::Runtime(boundary) => Outcome::Incomplete(Effect::RuntimeIpAddr {
                boundary: boundary.clone(),
            }),
            IpAddrSource::Ipv4New { octets, boundary } => {
                let mut values = [0u8; 4];
                for (slot, body) in values.iter_mut().zip(octets.iter()) {
                    let value = match reduce_ip_int_arg(body, ctx, boundary) {
                        Ok(Some(value)) => value,
                        Ok(None) => {
                            return Outcome::Incomplete(Effect::RuntimeIpAddr {
                                boundary: boundary.clone(),
                            });
                        }
                        Err(effect) => return Outcome::Incomplete(effect),
                    };
                    *slot = u8::try_from(value).unwrap_or_else(|_| {
                        panic!("Ipv4Addr::new segment is outside u8 at `{boundary}`")
                    });
                }
                Outcome::Complete(Desugared::Term(ip_term(LiteralIp::V4(Ipv4Addr::new(
                    values[0], values[1], values[2], values[3],
                )))))
            }
            IpAddrSource::Ipv6New { segments, boundary } => {
                let mut values = [0u16; 8];
                for (slot, body) in values.iter_mut().zip(segments.iter()) {
                    let value = match reduce_ip_int_arg(body, ctx, boundary) {
                        Ok(Some(value)) => value,
                        Ok(None) => {
                            return Outcome::Incomplete(Effect::RuntimeIpAddr {
                                boundary: boundary.clone(),
                            });
                        }
                        Err(effect) => return Outcome::Incomplete(effect),
                    };
                    *slot = u16::try_from(value).unwrap_or_else(|_| {
                        panic!("Ipv6Addr::new segment is outside u16 at `{boundary}`")
                    });
                }
                Outcome::Complete(Desugared::Term(ip_term(LiteralIp::V6(Ipv6Addr::new(
                    values[0], values[1], values[2], values[3], values[4], values[5], values[6],
                    values[7],
                )))))
            }
        }
    }
}

fn reduce_ip_int_arg(
    body: &SugarBody<TermFloor>,
    ctx: &SugarCtx,
    boundary: &str,
) -> Result<Option<i128>, Effect> {
    let term = match body.reduce(ctx) {
        Outcome::Complete(desugared) => desugared
            .into_term()
            .unwrap_or_else(|| panic!("IP address constructor argument completed as non-term")),
        Outcome::Incomplete(effect) => return Err(effect),
    };
    Ok(crate::const_fold_int_term(&term).or_else(|| {
        if crate::const_fold_u128_term(&term).is_some() {
            panic!("IP address constructor argument is u128-wide at `{boundary}`")
        }
        None
    }))
}

fn is_supported_property(method: &str) -> bool {
    matches!(
        method,
        "is_unspecified"
            | "is_loopback"
            | "is_private"
            | "is_link_local"
            | "is_global"
            | "is_multicast"
            | "is_broadcast"
            | "is_documentation"
            | "is_benchmarking"
            | "is_reserved"
            | "is_shared"
            | "is_unique_local"
            | "is_unicast_link_local"
            | "is_unicast_global"
            | "is_ipv4_mapped"
    )
}

fn call_path_type_and_method(call: &ExprCall) -> Option<(String, String)> {
    let Expr::Path(path) = strip_refs_groups(&call.func) else {
        return None;
    };
    path_type_and_method(&path.path)
}

fn resolve_literal_ip(expr: &Expr, scope: &TemporalScope, depth: usize) -> Option<LiteralIp> {
    match strip_refs_groups(expr) {
        Expr::MethodCall(call) if call.method == "unwrap" && call.args.is_empty() => {
            resolve_literal_ip(&call.receiver, scope, depth)
        }
        Expr::MethodCall(call) if call.method == "expect" && call.args.len() == 1 => {
            resolve_literal_ip(&call.receiver, scope, depth)
        }
        Expr::Call(call) => resolve_ip_call(call, scope, depth),
        Expr::Macro(expr_macro) => {
            if depth >= MAX_MACRO_EXPANSION_DEPTH {
                return None;
            }
            let name = expr_macro.mac.path.segments.last()?.ident.to_string();
            let rules = scope.macro_registry().lookup(&name)?;
            let expanded =
                crate::macro_expand::expand(&rules, expr_macro.mac.tokens.clone()).ok()?;
            let parsed: Expr = syn::parse2(expanded).ok()?;
            resolve_literal_ip(&parsed, scope, depth + 1)
        }
        Expr::Block(block) => match block.block.stmts.as_slice() {
            [syn::Stmt::Expr(tail, None)] => resolve_literal_ip(tail, scope, depth),
            _ => None,
        },
        Expr::Path(path) => resolve_ip_const_path(&path.path),
        Expr::Lit(_) | Expr::Array(_) | Expr::Tuple(_) => None,
        Expr::Paren(paren) => resolve_literal_ip(&paren.expr, scope, depth),
        Expr::Group(group) => resolve_literal_ip(&group.expr, scope, depth),
        _ => None,
    }
}

fn resolve_ip_const_path(path: &syn::Path) -> Option<LiteralIp> {
    let item = path.segments.last()?.ident.to_string();
    let ty = path
        .segments
        .iter()
        .rev()
        .skip(1)
        .find(|segment| matches!(segment.ident.to_string().as_str(), "Ipv4Addr" | "Ipv6Addr"))?
        .ident
        .to_string();
    match (ty.as_str(), item.as_str()) {
        ("Ipv4Addr", "LOCALHOST") => Some(LiteralIp::V4(Ipv4Addr::new(127, 0, 0, 1))),
        ("Ipv4Addr", "UNSPECIFIED") => Some(LiteralIp::V4(Ipv4Addr::new(0, 0, 0, 0))),
        ("Ipv4Addr", "BROADCAST") => Some(LiteralIp::V4(Ipv4Addr::new(255, 255, 255, 255))),
        ("Ipv6Addr", "LOCALHOST") => Some(LiteralIp::V6(Ipv6Addr::new(0, 0, 0, 0, 0, 0, 0, 1))),
        ("Ipv6Addr", "UNSPECIFIED") => Some(LiteralIp::V6(Ipv6Addr::new(0, 0, 0, 0, 0, 0, 0, 0))),
        _ => None,
    }
}

fn resolve_ip_call(call: &ExprCall, scope: &TemporalScope, depth: usize) -> Option<LiteralIp> {
    let Expr::Path(path) = strip_refs_groups(&call.func) else {
        return None;
    };
    let (ty, method) = path_type_and_method(&path.path)?;
    match (ty.as_str(), method.as_str(), call.args.len()) {
        ("IpAddr", "from_str", 1) => {
            let source = literal_string_value(call.args.first()?)?;
            IpAddr::from_str(&source).ok().map(LiteralIp::Any)
        }
        ("Ipv4Addr", "from_str", 1) => {
            let source = literal_string_value(call.args.first()?)?;
            Ipv4Addr::from_str(&source).ok().map(LiteralIp::V4)
        }
        ("Ipv6Addr", "from_str", 1) => {
            let source = literal_string_value(call.args.first()?)?;
            Ipv6Addr::from_str(&source).ok().map(LiteralIp::V6)
        }
        ("Ipv4Addr", "new", 4) => {
            let mut octets = [0u8; 4];
            for (slot, arg) in octets.iter_mut().zip(call.args.iter()) {
                *slot = u8::try_from(const_int(arg)?).ok()?;
            }
            Some(LiteralIp::V4(Ipv4Addr::new(
                octets[0], octets[1], octets[2], octets[3],
            )))
        }
        ("Ipv6Addr", "new", 8) => {
            let mut segments = [0u16; 8];
            for (slot, arg) in segments.iter_mut().zip(call.args.iter()) {
                *slot = u16::try_from(const_int(arg)?).ok()?;
            }
            Some(LiteralIp::V6(Ipv6Addr::new(
                segments[0],
                segments[1],
                segments[2],
                segments[3],
                segments[4],
                segments[5],
                segments[6],
                segments[7],
            )))
        }
        ("IpAddr", "from", 1) => match resolve_literal_ip(call.args.first()?, scope, depth)? {
            LiteralIp::V4(addr) => Some(LiteralIp::Any(IpAddr::V4(addr))),
            LiteralIp::V6(addr) => Some(LiteralIp::Any(IpAddr::V6(addr))),
            any @ LiteralIp::Any(_) => Some(any),
        },
        _ => None,
    }
}

fn ip_term(ip: LiteralIp) -> Rc<Term> {
    match ip {
        LiteralIp::Any(IpAddr::V4(addr)) => Rc::new(Term::Ctor {
            name: "ip:any-v4".to_string(),
            args: addr
                .octets()
                .into_iter()
                .map(|octet| num(i128::from(octet)))
                .collect(),
        }),
        LiteralIp::Any(IpAddr::V6(addr)) => Rc::new(Term::Ctor {
            name: "ip:any-v6".to_string(),
            args: addr
                .segments()
                .into_iter()
                .map(|segment| num(i128::from(segment)))
                .collect(),
        }),
        LiteralIp::V4(addr) => Rc::new(Term::Ctor {
            name: "ip:v4".to_string(),
            args: addr
                .octets()
                .into_iter()
                .map(|octet| num(i128::from(octet)))
                .collect(),
        }),
        LiteralIp::V6(addr) => Rc::new(Term::Ctor {
            name: "ip:v6".to_string(),
            args: addr
                .segments()
                .into_iter()
                .map(|segment| num(i128::from(segment)))
                .collect(),
        }),
    }
}

pub(crate) fn literal_ip_from_term(term: &Rc<Term>) -> Option<LiteralIp> {
    ip_from_term(term)
}

pub(crate) fn primitive_int_from_literal_ip(ip: LiteralIp, dst: IntKind, site: &str) -> Rc<Term> {
    let value = match ip {
        LiteralIp::V4(addr) if dst.name == "u32" => u128::from(u32::from_be_bytes(addr.octets())),
        LiteralIp::V6(addr) if dst.name == "u128" => u128::from_be_bytes(addr.octets()),
        _ => {
            panic!(
                "primitive From `{}` is not implemented for `{}` at `{}`",
                dst.name,
                ip.source_type_name(),
                site
            )
        }
    };
    ExactInt::Unsigned(value)
        .term_for_kind(dst)
        .unwrap_or_else(|| {
            panic!(
                "IP address floor value did not fit primitive From `{}` at `{}`",
                dst.name, site
            )
        })
}

fn ip_from_term(term: &Rc<Term>) -> Option<LiteralIp> {
    let Term::Ctor { name, args } = term.as_ref() else {
        return None;
    };
    match name.as_str() {
        "ip:any-v4" if args.len() == 4 => {
            let mut octets = [0u8; 4];
            for (slot, arg) in octets.iter_mut().zip(args.iter()) {
                *slot = u8::try_from(crate::const_fold_int_term(arg)?).ok()?;
            }
            Some(LiteralIp::Any(IpAddr::V4(Ipv4Addr::new(
                octets[0], octets[1], octets[2], octets[3],
            ))))
        }
        "ip:any-v6" if args.len() == 8 => {
            let mut segments = [0u16; 8];
            for (slot, arg) in segments.iter_mut().zip(args.iter()) {
                *slot = u16::try_from(crate::const_fold_int_term(arg)?).ok()?;
            }
            Some(LiteralIp::Any(IpAddr::V6(Ipv6Addr::new(
                segments[0],
                segments[1],
                segments[2],
                segments[3],
                segments[4],
                segments[5],
                segments[6],
                segments[7],
            ))))
        }
        "ip:v4" if args.len() == 4 => {
            let mut octets = [0u8; 4];
            for (slot, arg) in octets.iter_mut().zip(args.iter()) {
                *slot = u8::try_from(crate::const_fold_int_term(arg)?).ok()?;
            }
            Some(LiteralIp::V4(Ipv4Addr::new(
                octets[0], octets[1], octets[2], octets[3],
            )))
        }
        "ip:v6" if args.len() == 8 => {
            let mut segments = [0u16; 8];
            for (slot, arg) in segments.iter_mut().zip(args.iter()) {
                *slot = u16::try_from(crate::const_fold_int_term(arg)?).ok()?;
            }
            Some(LiteralIp::V6(Ipv6Addr::new(
                segments[0],
                segments[1],
                segments[2],
                segments[3],
                segments[4],
                segments[5],
                segments[6],
                segments[7],
            )))
        }
        _ => None,
    }
}

impl LiteralIp {
    fn source_type_name(self) -> &'static str {
        match self {
            LiteralIp::Any(_) => "IpAddr",
            LiteralIp::V4(_) => "Ipv4Addr",
            LiteralIp::V6(_) => "Ipv6Addr",
        }
    }
}

fn path_type_and_method(path: &syn::Path) -> Option<(String, String)> {
    let method = path.segments.last()?.ident.to_string();
    let ty = path
        .segments
        .iter()
        .rev()
        .skip(1)
        .find(|segment| {
            matches!(
                segment.ident.to_string().as_str(),
                "IpAddr" | "Ipv4Addr" | "Ipv6Addr"
            )
        })?
        .ident
        .to_string();
    Some((ty, method))
}

fn eval_property(ip: LiteralIp, method: &str) -> Option<bool> {
    match ip {
        LiteralIp::Any(IpAddr::V4(addr)) => eval_ip_addr_v4(addr, method),
        LiteralIp::Any(IpAddr::V6(addr)) => eval_ip_addr_v6(addr, method),
        LiteralIp::V4(addr) => eval_ipv4(addr, method),
        LiteralIp::V6(addr) => eval_ipv6(addr, method),
    }
}

fn eval_ip_addr_v4(addr: Ipv4Addr, method: &str) -> Option<bool> {
    match method {
        "is_unspecified" => Some(ipv4_is_unspecified(addr)),
        "is_loopback" => Some(ipv4_is_loopback(addr)),
        "is_global" => Some(ipv4_is_global(addr)),
        "is_multicast" => Some(ipv4_is_multicast(addr)),
        "is_documentation" => Some(ipv4_is_documentation(addr)),
        "is_benchmarking" => Some(ipv4_is_benchmarking(addr)),
        _ => None,
    }
}

fn eval_ip_addr_v6(addr: Ipv6Addr, method: &str) -> Option<bool> {
    match method {
        "is_unspecified" => Some(ipv6_is_unspecified(addr)),
        "is_loopback" => Some(ipv6_is_loopback(addr)),
        "is_global" => Some(ipv6_is_global(addr)),
        "is_multicast" => Some(ipv6_is_multicast(addr)),
        "is_documentation" => Some(ipv6_is_documentation(addr)),
        "is_benchmarking" => Some(ipv6_is_benchmarking(addr)),
        _ => None,
    }
}

fn eval_ipv4(addr: Ipv4Addr, method: &str) -> Option<bool> {
    match method {
        "is_unspecified" => Some(ipv4_is_unspecified(addr)),
        "is_loopback" => Some(ipv4_is_loopback(addr)),
        "is_private" => Some(ipv4_is_private(addr)),
        "is_link_local" => Some(ipv4_is_link_local(addr)),
        "is_global" => Some(ipv4_is_global(addr)),
        "is_multicast" => Some(ipv4_is_multicast(addr)),
        "is_broadcast" => Some(ipv4_is_broadcast(addr)),
        "is_documentation" => Some(ipv4_is_documentation(addr)),
        "is_benchmarking" => Some(ipv4_is_benchmarking(addr)),
        "is_reserved" => Some(ipv4_is_reserved(addr)),
        "is_shared" => Some(ipv4_is_shared(addr)),
        _ => None,
    }
}

fn eval_ipv6(addr: Ipv6Addr, method: &str) -> Option<bool> {
    match method {
        "is_unspecified" => Some(ipv6_is_unspecified(addr)),
        "is_loopback" => Some(ipv6_is_loopback(addr)),
        "is_unique_local" => Some(ipv6_is_unique_local(addr)),
        "is_global" => Some(ipv6_is_global(addr)),
        "is_unicast_link_local" => Some(ipv6_is_unicast_link_local(addr)),
        "is_unicast_global" => Some(ipv6_is_unicast_global(addr)),
        "is_documentation" => Some(ipv6_is_documentation(addr)),
        "is_benchmarking" => Some(ipv6_is_benchmarking(addr)),
        "is_multicast" => Some(ipv6_is_multicast(addr)),
        "is_ipv4_mapped" => Some(ipv6_is_ipv4_mapped(addr)),
        _ => None,
    }
}

fn ipv4_is_unspecified(addr: Ipv4Addr) -> bool {
    addr.octets() == [0, 0, 0, 0]
}

fn ipv4_is_loopback(addr: Ipv4Addr) -> bool {
    addr.octets()[0] == 127
}

fn ipv4_is_private(addr: Ipv4Addr) -> bool {
    matches!(
        addr.octets(),
        [10, ..] | [172, 16..=31, ..] | [192, 168, ..]
    )
}

fn ipv4_is_link_local(addr: Ipv4Addr) -> bool {
    matches!(addr.octets(), [169, 254, ..])
}

fn ipv4_is_shared(addr: Ipv4Addr) -> bool {
    let [a, b, ..] = addr.octets();
    a == 100 && (b & 0b1100_0000) == 0b0100_0000
}

fn ipv4_is_benchmarking(addr: Ipv4Addr) -> bool {
    let [a, b, ..] = addr.octets();
    a == 198 && (b & 0xfe) == 18
}

fn ipv4_is_reserved(addr: Ipv4Addr) -> bool {
    addr.octets()[0] & 240 == 240 && !ipv4_is_broadcast(addr)
}

fn ipv4_is_multicast(addr: Ipv4Addr) -> bool {
    matches!(addr.octets()[0], 224..=239)
}

fn ipv4_is_broadcast(addr: Ipv4Addr) -> bool {
    addr.octets() == [255, 255, 255, 255]
}

fn ipv4_is_documentation(addr: Ipv4Addr) -> bool {
    matches!(
        addr.octets(),
        [192, 0, 2, _] | [198, 51, 100, _] | [203, 0, 113, _]
    )
}

fn ipv4_is_global(addr: Ipv4Addr) -> bool {
    let [a, b, c, d] = addr.octets();
    !(a == 0
        || ipv4_is_private(addr)
        || ipv4_is_shared(addr)
        || ipv4_is_loopback(addr)
        || ipv4_is_link_local(addr)
        || (a == 192 && b == 0 && c == 0 && d != 9 && d != 10)
        || ipv4_is_documentation(addr)
        || ipv4_is_benchmarking(addr)
        || ipv4_is_reserved(addr)
        || ipv4_is_broadcast(addr))
}

fn ipv6_is_unspecified(addr: Ipv6Addr) -> bool {
    addr.octets() == [0; 16]
}

fn ipv6_is_loopback(addr: Ipv6Addr) -> bool {
    u128::from_be_bytes(addr.octets()) == 1
}

fn ipv6_is_unique_local(addr: Ipv6Addr) -> bool {
    (addr.segments()[0] & 0xfe00) == 0xfc00
}

fn ipv6_is_unicast_link_local(addr: Ipv6Addr) -> bool {
    (addr.segments()[0] & 0xffc0) == 0xfe80
}

fn ipv6_is_documentation(addr: Ipv6Addr) -> bool {
    matches!(
        addr.segments(),
        [0x2001, 0x0db8, ..] | [0x3fff, 0x0000..=0x0fff, ..]
    )
}

fn ipv6_is_benchmarking(addr: Ipv6Addr) -> bool {
    matches!(addr.segments(), [0x2001, 0x0002, 0, ..])
}

fn ipv6_is_multicast(addr: Ipv6Addr) -> bool {
    (addr.segments()[0] & 0xff00) == 0xff00
}

fn ipv6_is_ipv4_mapped(addr: Ipv6Addr) -> bool {
    matches!(addr.segments(), [0, 0, 0, 0, 0, 0xffff, _, _])
}

fn ipv6_is_unicast(addr: Ipv6Addr) -> bool {
    !ipv6_is_multicast(addr)
}

fn ipv6_is_unicast_global(addr: Ipv6Addr) -> bool {
    ipv6_is_unicast(addr)
        && !ipv6_is_loopback(addr)
        && !ipv6_is_unicast_link_local(addr)
        && !ipv6_is_unique_local(addr)
        && !ipv6_is_unspecified(addr)
        && !ipv6_is_documentation(addr)
        && !ipv6_is_benchmarking(addr)
}

fn ipv6_is_global(addr: Ipv6Addr) -> bool {
    let segments = addr.segments();
    let value = u128::from_be_bytes(addr.octets());
    !(ipv6_is_unspecified(addr)
        || ipv6_is_loopback(addr)
        || matches!(segments, [0, 0, 0, 0, 0, 0xffff, _, _])
        || matches!(segments, [0x64, 0xff9b, 1, _, _, _, _, _])
        || matches!(segments, [0x100, 0, 0, 0, _, _, _, _])
        || (matches!(segments, [0x2001, b, _, _, _, _, _, _] if b < 0x200)
            && !(value == 0x2001_0001_0000_0000_0000_0000_0000_0001
                || value == 0x2001_0001_0000_0000_0000_0000_0000_0002
                || matches!(segments, [0x2001, 3, _, _, _, _, _, _])
                || matches!(segments, [0x2001, 4, 0x112, _, _, _, _, _])
                || matches!(segments, [0x2001, b, _, _, _, _, _, _] if (0x20..=0x3f).contains(&b))))
        || matches!(segments, [0x2002, _, _, _, _, _, _, _])
        || ipv6_is_documentation(addr)
        || matches!(segments, [0x5f00, ..])
        || ipv6_is_unique_local(addr)
        || ipv6_is_unicast_link_local(addr))
}

fn compact_warrant_fragment(site: &str) -> String {
    site.chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || matches!(ch, '_' | ':' | '.') {
                ch
            } else {
                '_'
            }
        })
        .collect()
}

fn ip_addr_gap(reason: &str) -> ! {
    panic!("ip_addr property did not reach a lawful IP floor: {reason}")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ip_floor_roundtrip_preserves_concrete_ipv4_receiver_type() {
        let ip = LiteralIp::V4(Ipv4Addr::new(255, 255, 255, 255));

        assert_eq!(ip_from_term(&ip_term(ip)), Some(ip));
    }

    #[test]
    fn ip_floor_roundtrip_preserves_enum_ipv4_receiver_type() {
        let ip = LiteralIp::Any(IpAddr::V4(Ipv4Addr::new(127, 0, 0, 1)));

        assert_eq!(ip_from_term(&ip_term(ip)), Some(ip));
    }

    #[test]
    fn ip_floor_owns_ipv6_to_u128_from_value() {
        let ip = LiteralIp::V6(Ipv6Addr::new(
            0x1122, 0x3344, 0x5566, 0x7788, 0x99aa, 0xbbcc, 0xddee, 0xff11,
        ));
        let kind = crate::sugar::int_literal::primitive_int_kind("u128").unwrap();
        let term = primitive_int_from_literal_ip(ip, kind, "test");

        assert_eq!(
            crate::const_fold_u128_term(&term),
            Some(0x112233445566778899aabbccddeeff11u128)
        );
    }
}
