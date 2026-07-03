# Equational Portfolio Extension

**Status:** v0.1.0 implementation spec
**Date:** 2026-05-10
**Owner:** verifier crate and IR compiler crates

## 1. Scope

This extension adds a Maude backend to the prove portfolio for obligations whose compiler-declared coverage is exactly `equational_theory`.

The IR remains solver-neutral. The Maude compiler is the authority for this coverage class. The verifier remains the authority for composing Maude with the rest of the portfolio, including the CeTA gate that controls when Maude normal-form equality can be trusted.

References:

- Multi-Solver Protocol v2, section 1: compiler authority over sound coverage.
- Language Signature Protocol, section 1.2: `EquationMemento`.
- Language Signature Protocol, section 2: homomorphism obligations include target-theory entailment.
- Language Signature Protocol, section 6: morphism composition factors through discharged obligations.
- Paper 13, Lemma 7: equational reasoning by catalog equations.
- Paper 13, Lemma 8: finitely presented algebraic languages are substrate-presentable.

## 2. Coverage Declaration

The Maude compiler declares support for:

```
equational_theory
```

It does not declare support for dependent types, higher-order terms, induction over infinite domains, arithmetic beyond equations supplied by the caller, or general first-order logic. Inputs outside `equational_theory` are rejected rather than silently compiled.

## 3. Lowering

An equational obligation is an IR-JSON object with:

- `kind = "atomic"` and `name = "equational_theory"`, or `kind = "equational_theory"`.
- `theory`: a finite presentation with sorts, optional subsorts, operators, variables, and equations.
- `obligation`: a pair `{ lhs, rhs }`.

The compiler emits one Maude functional module:

```
fmod <NAME> is
  sort <SORT> .
  op <OP> : <ARGS> -> <RESULT> .
  vars <VARS> : <SORT> .
  eq <LHS> = <RHS> .
endfm
```

The module is followed by three queries:

```
red in <NAME> : <lhs> .
red in <NAME> : <rhs> .
search in <NAME> : <lhs> =>* <rhs> .
```

The two `red` queries compare canonical normal forms. The `search` query is a positive reachability witness. The compiler output is deterministic for byte-for-byte testing.

## 4. Verdict Semantics

The Maude adapter parses the solver output as follows:

- If the two `red` queries produce syntactically equal normal forms, Maude has a reduce witness.
- If `search` reports a solution, Maude has a search witness.
- If neither condition holds, the Maude verdict is `Unknown`, represented by the existing verifier verdict `Undecidable`.
- If Maude errors or times out, the verdict is `Undecidable`.

The `search` witness is always positive evidence for entailment and does not need the CeTA gate.

The `reduce` witness is trusted only when the CeTA gate accepts the equation set as terminating and confluent. Without that gate, normal forms might be non-unique or might not exist, so equal or unequal reduce results are not enough to decide the obligation.

## 5. AC-Builtin Handling

Maude operator attributes such as `assoc` and `comm` are emitted as native Maude operator attributes:

```
op _+_ : Elt Elt -> Elt [assoc comm] .
```

Equations that are handled solely by Maude builtin AC matching are not emitted to the TRS gate. The gate applies to user equations read left-to-right as rewrite rules. This keeps pure AC operator declarations from being rejected as non-terminating rewrite systems.

## 6. CeTA Gate

For every user equation `lhs = rhs`, the gate reads the equation left-to-right as a TRS rule:

```
lhs -> rhs
```

The gate flow is:

1. Emit the TRS in WST format for the termination prover and confluence checker.
2. Run a termination prover such as AProVE, Wanda, or TTT2 to produce a CPF certificate.
3. Run a confluence checker such as CSI, or AProVE in confluence mode, to produce a CPF certificate.
4. Verify both certificates with CeTA.
5. Accept the Maude `reduce` witness only if both CeTA checks accept.

If any prover, checker, certificate write, CeTA check, or timeout fails, the `reduce` witness is discarded. The portfolio then treats the Maude result as `Undecidable` unless the `search` witness already discharged the obligation. Chain and portfolio modes can then fall through to Vampire, Coq, or another configured solver.

## 7. Receipt Shape

The Maude adapter records a two-part receipt in the `SolveResult`
stdout evidence sidecar:

```json
{
  "maude_verdict": {
    "maude_version": "Maude 3.5.1",
    "module_cid": "blake3-512:...",
    "queries": {
      "lhs_reduce": "red in M : lhs .",
      "rhs_reduce": "red in M : rhs .",
      "search": "search in M : lhs =>* rhs ."
    },
    "normal_forms": ["nf_lhs", "nf_rhs"],
    "decision": "reduce_equal",
    "verdict": "discharged"
  },
  "ceta_gate": {
    "termination_cert_cid": "blake3-512:...",
    "confluence_cert_cid": "blake3-512:...",
    "ceta_accepted": true,
    "bypassed": false,
    "error": ""
  }
}
```

The module CID is `BLAKE3-512(JCS(<lowered module source as a JSON string>))` using `sugar-canonicalizer`. Certificate CIDs are `BLAKE3-512` over the certificate bytes using the same canonicalizer hash helper.

## 8. Dispatch

Configurations may place `maude` in any existing plan shape:

```toml
[solvers]
mode = "first-wins"
portfolio = ["maude", "z3", "cvc5", "vampire", "coq"]

[solvers.maude]
binary = "maude"
ir_compiler = "maude"
ceta_gate = true
ceta_binary = "ceta"
termination_prover = "aprove"
confluence_checker = "csi"
timeout_seconds = 30
```

Dispatch mode may route equational obligations directly:

```toml
[solvers.dispatch]
"equational-theory" = "maude"
default = "z3"
```

The verifier passes raw IR-JSON to non-SMT compilers and SMT-LIB to SMT compilers. This preserves the current solver trait while letting Maude and Coq compile from the original formula.
