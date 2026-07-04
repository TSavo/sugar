# C Lifter Family Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first slice of the C lifter family: a shared C lift core, preserved C LSP behavior through that core, first-class opacity/refusal output, a sparse lifter, a minimal assertions lifter, and deterministic composition tests.

**Architecture:** `implementations/c/sugar-lift-core` owns shared C facts, source loci, result streams, and JSON helpers. Standalone lifters such as `sugar-lift-c-sparse` and `sugar-lift-c-assertions` consume core facts and emit only their own semantic declarations. The existing `sugar-lsp-c` binary should call the core so current behavior is preserved while new lifters build on the same substrate.

**Tech Stack:** C11, existing C Makefile style, the new shared core JSON/result helpers, POSIX shell integration tests, and per-lifter `.sugar/lift/.../manifest.toml` manifests.

---

## File Structure

- Create `implementations/c/sugar-lift-core/Makefile`: builds and tests the shared core.
- Create `implementations/c/sugar-lift-core/include/sugar/c_lift_core.h`: public fact/result API shared by C-family lifters.
- Create `implementations/c/sugar-lift-core/src/core.c`: result management, JSON emission, append helpers.
- Create `implementations/c/sugar-lift-core/src/parser.c`: temporary regex/parser backend fact extraction, moved out of `sugar-lsp-c`.
- Create `implementations/c/sugar-lift-core/tests/test_runner.c`: focused unit tests for result streams, facts, opacity, refusals, and composition.
- Modify `implementations/c/sugar-lsp-c/Makefile`: link the LSP binary against the shared core sources.
- Modify `implementations/c/sugar-lsp-c/main.c`: delegate parse-source behavior to `sugar-lift-core`.
- Create `implementations/c/sugar-lift-c-sparse/Makefile`: builds/tests the sparse lifter.
- Create `implementations/c/sugar-lift-c-sparse/src/main.c`: JSON-RPC-ish CLI for sparse lifter.
- Create `implementations/c/sugar-lift-c-sparse/src/sparse.c`: sparse semantic extraction.
- Create `implementations/c/sugar-lift-c-sparse/tests/fixtures/sparse_basic.c`: sparse annotation fixture.
- Create `implementations/c/sugar-lift-c-sparse/tests/integration.sh`: sparse lifter integration test.
- Create `implementations/c/.sugar/lift/c-sparse/manifest.toml`: lifter identity manifest.
- Create `implementations/c/sugar-lift-c-assertions/Makefile`: builds/tests the assertions lifter.
- Create `implementations/c/sugar-lift-c-assertions/src/main.c`: JSON-RPC-ish CLI for assertions lifter.
- Create `implementations/c/sugar-lift-c-assertions/src/assertions.c`: assertion macro semantic extraction.
- Create `implementations/c/sugar-lift-c-assertions/tests/fixtures/assertions_basic.c`: assertion fixture.
- Create `implementations/c/sugar-lift-c-assertions/tests/integration.sh`: assertions lifter integration test.
- Create `implementations/c/.sugar/lift/c-assertions/manifest.toml`: lifter identity manifest.
- Create `implementations/c/sugar-lift-composition/Makefile`: composition test runner.
- Create `implementations/c/sugar-lift-composition/tests/fixtures/sparse_and_assertions.c`: shared fixture for two lifters.
- Create `implementations/c/sugar-lift-composition/tests/integration.sh`: runs sparse and assertions lifters over the same source and verifies outputs remain separate and deterministic.
- Modify top-level `Makefile`: include the new packages in `build-c` and `test-c`.

---

### Task 1: Shared Core Result API

**Files:**
- Create: `implementations/c/sugar-lift-core/include/sugar/c_lift_core.h`
- Create: `implementations/c/sugar-lift-core/src/core.c`
- Create: `implementations/c/sugar-lift-core/tests/test_runner.c`
- Create: `implementations/c/sugar-lift-core/Makefile`

- [ ] **Step 1: Write the failing test**

Create `implementations/c/sugar-lift-core/tests/test_runner.c` with a test that uses the core API before it exists:

```c
#include "sugar/c_lift_core.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int failures = 0;

static void assert_eq(const char *got, const char *want, const char *label) {
    if (strcmp(got, want) != 0) {
        fprintf(stderr, "FAIL: %s\nwant: %s\ngot:  %s\n", label, want, got);
        failures++;
    }
}

static void test_empty_result_json(void) {
    pk_c_lift_result *r = pk_c_lift_result_new();
    char *json = pk_c_lift_result_to_json(r);
    assert_eq(json,
        "{\"declarations\":[],\"callEdges\":[],\"diagnostics\":[],\"opacityReport\":[],\"refusals\":[]}",
        "empty result JSON");
    free(json);
    pk_c_lift_result_free(r);
}

int main(void) {
    test_empty_result_json();
    if (failures != 0) {
        fprintf(stderr, "%d failures\n", failures);
        return 1;
    }
    puts("sugar-lift-core tests passed");
    return 0;
}
```

- [ ] **Step 2: Add the package Makefile**

Create `implementations/c/sugar-lift-core/Makefile`:

```makefile
# SPDX-License-Identifier: MIT OR Apache-2.0

CC = cc
CFLAGS = -Wall -Wextra -Wpedantic -std=c11 -Iinclude -g

SRC = src/core.c src/parser.c
OBJ = $(SRC:.c=.o)
TEST = tests/test_runner

.PHONY: all test clean

all: test

test: $(TEST)
	./$(TEST)

$(TEST): $(OBJ) tests/test_runner.c
	$(CC) $(CFLAGS) -o $@ $(OBJ) tests/test_runner.c

%.o: %.c include/sugar/c_lift_core.h
	$(CC) $(CFLAGS) -c $< -o $@

clean:
	rm -f $(OBJ) $(TEST)
```

Create an empty parser file so the Makefile has the planned source set:

```c
#include "sugar/c_lift_core.h"
```

- [ ] **Step 3: Run the test to verify it fails**

Run:

```bash
make -C implementations/c/sugar-lift-core test
```

Expected: compile failure because `sugar/c_lift_core.h` and the result API do not exist.

- [ ] **Step 4: Implement the minimal core API**

Create `implementations/c/sugar-lift-core/include/sugar/c_lift_core.h`:

```c
/* SPDX-License-Identifier: MIT OR Apache-2.0 */
#ifndef SUGAR_C_LIFT_CORE_H
#define SUGAR_C_LIFT_CORE_H

#include <stddef.h>

typedef struct {
    char *path;
    int line;
    int column;
} pk_c_locus;

typedef struct {
    char **items;
    size_t len;
    size_t cap;
} pk_c_json_array;

typedef struct pk_c_lift_result {
    pk_c_json_array declarations;
    pk_c_json_array call_edges;
    pk_c_json_array diagnostics;
    pk_c_json_array opacity_report;
    pk_c_json_array refusals;
} pk_c_lift_result;

pk_c_lift_result *pk_c_lift_result_new(void);
void pk_c_lift_result_free(pk_c_lift_result *result);
int pk_c_lift_result_add_declaration(pk_c_lift_result *result, const char *json);
int pk_c_lift_result_add_call_edge(pk_c_lift_result *result, const char *json);
int pk_c_lift_result_add_diagnostic(pk_c_lift_result *result, const char *json);
int pk_c_lift_result_add_opacity(pk_c_lift_result *result, const char *json);
int pk_c_lift_result_add_refusal(pk_c_lift_result *result, const char *json);
char *pk_c_lift_result_to_json(const pk_c_lift_result *result);

#endif
```

Create `implementations/c/sugar-lift-core/src/core.c`:

```c
/* SPDX-License-Identifier: MIT OR Apache-2.0 */
#include "sugar/c_lift_core.h"
#include <stdlib.h>
#include <string.h>

typedef struct {
    char *data;
    size_t len;
    size_t cap;
} pk_c_buf;

static char *pk_c_strdup(const char *s) {
    size_t n = strlen(s) + 1;
    char *out = (char *)malloc(n);
    if (out) memcpy(out, s, n);
    return out;
}

static void buf_init(pk_c_buf *buf) {
    buf->cap = 256;
    buf->len = 0;
    buf->data = (char *)malloc(buf->cap);
    if (buf->data) buf->data[0] = '\0';
}

static void buf_grow(pk_c_buf *buf, size_t need) {
    if (buf->len + need + 1 <= buf->cap) return;
    size_t next = buf->cap * 2;
    while (next < buf->len + need + 1) next *= 2;
    char *data = (char *)realloc(buf->data, next);
    if (!data) return;
    buf->data = data;
    buf->cap = next;
}

static void buf_append(pk_c_buf *buf, const char *s) {
    size_t n = strlen(s);
    buf_grow(buf, n);
    memcpy(buf->data + buf->len, s, n + 1);
    buf->len += n;
}

static void array_init(pk_c_json_array *array) {
    array->items = NULL;
    array->len = 0;
    array->cap = 0;
}

static void array_free(pk_c_json_array *array) {
    for (size_t i = 0; i < array->len; i++) free(array->items[i]);
    free(array->items);
    array->items = NULL;
    array->len = 0;
    array->cap = 0;
}

static int array_add(pk_c_json_array *array, const char *json) {
    if (array->len == array->cap) {
        size_t next = array->cap == 0 ? 4 : array->cap * 2;
        char **items = (char **)realloc(array->items, next * sizeof(char *));
        if (!items) return 0;
        array->items = items;
        array->cap = next;
    }
    array->items[array->len] = pk_c_strdup(json);
    if (!array->items[array->len]) return 0;
    array->len++;
    return 1;
}

static void append_array(pk_c_buf *buf, const pk_c_json_array *array) {
    buf_append(buf, "[");
    for (size_t i = 0; i < array->len; i++) {
        if (i > 0) buf_append(buf, ",");
        buf_append(buf, array->items[i]);
    }
    buf_append(buf, "]");
}

pk_c_lift_result *pk_c_lift_result_new(void) {
    pk_c_lift_result *result = (pk_c_lift_result *)calloc(1, sizeof(pk_c_lift_result));
    if (!result) return NULL;
    array_init(&result->declarations);
    array_init(&result->call_edges);
    array_init(&result->diagnostics);
    array_init(&result->opacity_report);
    array_init(&result->refusals);
    return result;
}

void pk_c_lift_result_free(pk_c_lift_result *result) {
    if (!result) return;
    array_free(&result->declarations);
    array_free(&result->call_edges);
    array_free(&result->diagnostics);
    array_free(&result->opacity_report);
    array_free(&result->refusals);
    free(result);
}

int pk_c_lift_result_add_declaration(pk_c_lift_result *result, const char *json) {
    return array_add(&result->declarations, json);
}

int pk_c_lift_result_add_call_edge(pk_c_lift_result *result, const char *json) {
    return array_add(&result->call_edges, json);
}

int pk_c_lift_result_add_diagnostic(pk_c_lift_result *result, const char *json) {
    return array_add(&result->diagnostics, json);
}

int pk_c_lift_result_add_opacity(pk_c_lift_result *result, const char *json) {
    return array_add(&result->opacity_report, json);
}

int pk_c_lift_result_add_refusal(pk_c_lift_result *result, const char *json) {
    return array_add(&result->refusals, json);
}

char *pk_c_lift_result_to_json(const pk_c_lift_result *result) {
    pk_c_buf buf;
    buf_init(&buf);
    buf_append(&buf, "{\"declarations\":");
    append_array(&buf, &result->declarations);
    buf_append(&buf, ",\"callEdges\":");
    append_array(&buf, &result->call_edges);
    buf_append(&buf, ",\"diagnostics\":");
    append_array(&buf, &result->diagnostics);
    buf_append(&buf, ",\"opacityReport\":");
    append_array(&buf, &result->opacity_report);
    buf_append(&buf, ",\"refusals\":");
    append_array(&buf, &result->refusals);
    buf_append(&buf, "}");
    return buf.data;
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run:

```bash
make -C implementations/c/sugar-lift-core test
```

Expected: `sugar-lift-core tests passed`.

- [ ] **Step 6: Commit**

```bash
git add implementations/c/sugar-lift-core
git commit -m "feat(c): add lift core result streams"
```

---

### Task 2: Core Parser Facts

**Files:**
- Modify: `implementations/c/sugar-lift-core/include/sugar/c_lift_core.h`
- Modify: `implementations/c/sugar-lift-core/src/parser.c`
- Modify: `implementations/c/sugar-lift-core/tests/test_runner.c`

- [ ] **Step 1: Write the failing test**

Append this test to `tests/test_runner.c` and call it from `main` after `test_empty_result_json()`:

```c
static void test_parse_functions_and_macros(void) {
    const char *source =
        "int helper(int x) { return x + 1; }\n"
        "int compute(int y) {\n"
        "    WARN_ON(y < 0);\n"
        "    return helper(y);\n"
        "}\n";
    pk_c_source_facts *facts = pk_c_parse_source("fixture.c", source);
    if (!facts) {
        fprintf(stderr, "FAIL: parse returned null\n");
        failures++;
        return;
    }
    if (facts->n_functions != 2) {
        fprintf(stderr, "FAIL: expected 2 functions, got %zu\n", facts->n_functions);
        failures++;
    }
    assert_eq(facts->functions[0].name, "helper", "first function name");
    assert_eq(facts->functions[1].name, "compute", "second function name");
    if (facts->n_macro_calls != 1) {
        fprintf(stderr, "FAIL: expected 1 macro call, got %zu\n", facts->n_macro_calls);
        failures++;
    } else {
        assert_eq(facts->macro_calls[0].name, "WARN_ON", "macro call name");
        assert_eq(facts->macro_calls[0].enclosing_function, "compute", "macro enclosing function");
    }
    if (facts->n_call_sites != 1) {
        fprintf(stderr, "FAIL: expected 1 call site, got %zu\n", facts->n_call_sites);
        failures++;
    } else {
        assert_eq(facts->call_sites[0].callee, "helper", "call callee");
        assert_eq(facts->call_sites[0].caller, "compute", "call caller");
    }
    pk_c_source_facts_free(facts);
}
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
make -C implementations/c/sugar-lift-core test
```

Expected: compile failure for missing `pk_c_source_facts`, `pk_c_parse_source`, and `pk_c_source_facts_free`.

- [ ] **Step 3: Add the fact model API**

Add these definitions to `c_lift_core.h` after the `pk_c_lift_result` typedef and before the result function declarations:

```c
typedef struct {
    char *name;
    pk_c_locus locus;
    int has_body;
    int has_contract_annotation;
} pk_c_function_fact;

typedef struct {
    char *name;
    char *enclosing_function;
    char *argument_text;
    pk_c_locus locus;
} pk_c_macro_call_fact;

typedef struct {
    char *caller;
    char *callee;
    pk_c_locus locus;
} pk_c_call_site_fact;

typedef struct {
    pk_c_function_fact *functions;
    size_t n_functions;
    size_t cap_functions;
    pk_c_macro_call_fact *macro_calls;
    size_t n_macro_calls;
    size_t cap_macro_calls;
    pk_c_call_site_fact *call_sites;
    size_t n_call_sites;
    size_t cap_call_sites;
    pk_c_lift_result *extraction_result;
} pk_c_source_facts;

pk_c_source_facts *pk_c_parse_source(const char *path, const char *source);
void pk_c_source_facts_free(pk_c_source_facts *facts);
```

- [ ] **Step 4: Implement the temporary parser backend**

Replace `implementations/c/sugar-lift-core/src/parser.c` with this regex-backed fact extractor:

```c
/* SPDX-License-Identifier: MIT OR Apache-2.0 */
#define _GNU_SOURCE
#include "sugar/c_lift_core.h"
#include <regex.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static char *dup_string(const char *s) {
    size_t n = strlen(s) + 1;
    char *out = (char *)malloc(n);
    if (out) memcpy(out, s, n);
    return out;
}

static int is_keyword(const char *name) {
    static const char *keywords[] = {
        "if", "else", "for", "while", "do", "switch", "case", "return",
        "break", "continue", "goto", "sizeof", "typeof", "alignof",
        "static", "extern", "const", "volatile", "inline", "register",
        "void", "int", "char", "short", "long", "float", "double",
        "unsigned", "signed", "struct", "union", "enum", "typedef",
        NULL
    };
    for (int i = 0; keywords[i]; i++) {
        if (strcmp(name, keywords[i]) == 0) return 1;
    }
    return 0;
}

static int is_contract_annotation(const char *line) {
    while (*line == ' ' || *line == '\t') line++;
    return strncmp(line, "//sugar:contract", 19) == 0;
}

static int is_blank_line(const char *line) {
    for (const char *p = line; *p; p++) {
        if (*p != ' ' && *p != '\t' && *p != '\r' && *p != '\n') return 0;
    }
    return 1;
}

static int is_macro_name(const char *name) {
    return (name[0] >= 'A' && name[0] <= 'Z') || strncmp(name, "KUNIT_", 6) == 0;
}

static void set_locus(pk_c_locus *locus, const char *path, int line, int column) {
    locus->path = dup_string(path ? path : "");
    locus->line = line;
    locus->column = column;
}

static int grow_functions(pk_c_source_facts *facts) {
    if (facts->n_functions < facts->cap_functions) return 1;
    size_t next = facts->cap_functions == 0 ? 8 : facts->cap_functions * 2;
    pk_c_function_fact *items =
        (pk_c_function_fact *)realloc(facts->functions, next * sizeof(pk_c_function_fact));
    if (!items) return 0;
    facts->functions = items;
    facts->cap_functions = next;
    return 1;
}

static int grow_macros(pk_c_source_facts *facts) {
    if (facts->n_macro_calls < facts->cap_macro_calls) return 1;
    size_t next = facts->cap_macro_calls == 0 ? 8 : facts->cap_macro_calls * 2;
    pk_c_macro_call_fact *items =
        (pk_c_macro_call_fact *)realloc(facts->macro_calls, next * sizeof(pk_c_macro_call_fact));
    if (!items) return 0;
    facts->macro_calls = items;
    facts->cap_macro_calls = next;
    return 1;
}

static int grow_calls(pk_c_source_facts *facts) {
    if (facts->n_call_sites < facts->cap_call_sites) return 1;
    size_t next = facts->cap_call_sites == 0 ? 16 : facts->cap_call_sites * 2;
    pk_c_call_site_fact *items =
        (pk_c_call_site_fact *)realloc(facts->call_sites, next * sizeof(pk_c_call_site_fact));
    if (!items) return 0;
    facts->call_sites = items;
    facts->cap_call_sites = next;
    return 1;
}

static void append_function(
    pk_c_source_facts *facts,
    const char *path,
    const char *name,
    int line,
    int column,
    int has_body,
    int has_contract_annotation)
{
    if (!grow_functions(facts)) return;
    pk_c_function_fact *fact = &facts->functions[facts->n_functions++];
    fact->name = dup_string(name);
    set_locus(&fact->locus, path, line, column);
    fact->has_body = has_body;
    fact->has_contract_annotation = has_contract_annotation;
}

static void append_macro(
    pk_c_source_facts *facts,
    const char *path,
    const char *name,
    const char *enclosing_function,
    int line,
    int column)
{
    if (!grow_macros(facts)) return;
    pk_c_macro_call_fact *fact = &facts->macro_calls[facts->n_macro_calls++];
    fact->name = dup_string(name);
    fact->enclosing_function = dup_string(enclosing_function);
    fact->argument_text = dup_string("");
    set_locus(&fact->locus, path, line, column);
}

static void append_call_site(
    pk_c_source_facts *facts,
    const char *path,
    const char *caller,
    const char *callee,
    int line,
    int column)
{
    if (!grow_calls(facts)) return;
    pk_c_call_site_fact *fact = &facts->call_sites[facts->n_call_sites++];
    fact->caller = dup_string(caller);
    fact->callee = dup_string(callee);
    set_locus(&fact->locus, path, line, column);
}

static int line_opens_allman_body(
    const char **lines_start,
    const int *lines_len,
    int n_lines,
    int i)
{
    char nextline[4096];
    for (int j = i + 1; j < n_lines && j < i + 4; j++) {
        int jlen = lines_len[j];
        if (jlen >= (int)sizeof(nextline)) jlen = (int)sizeof(nextline) - 1;
        memcpy(nextline, lines_start[j], (size_t)jlen);
        nextline[jlen] = '\0';
        if (is_blank_line(nextline)) continue;
        for (int ci = 0; nextline[ci]; ci++) {
            if (nextline[ci] == ' ' || nextline[ci] == '\t') continue;
            return nextline[ci] == '{';
        }
    }
    return 0;
}

pk_c_source_facts *pk_c_parse_source(const char *path, const char *source) {
    pk_c_source_facts *facts = (pk_c_source_facts *)calloc(1, sizeof(pk_c_source_facts));
    if (!facts) return NULL;
    facts->extraction_result = pk_c_lift_result_new();

    regex_t re_funcdef;
    regex_t re_callsite;
    int r = regcomp(&re_funcdef,
        "^[[:space:]]*[A-Za-z_][A-Za-z0-9_ *]*[[:space:]]+([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*\\(",
        REG_EXTENDED);
    if (r != 0) {
        if (facts->extraction_result) {
            pk_c_lift_result_add_diagnostic(facts->extraction_result,
                "{\"message\":\"regex compile failed: function definitions\"}");
        }
        return facts;
    }
    r = regcomp(&re_callsite, "([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*\\(", REG_EXTENDED);
    if (r != 0) {
        regfree(&re_funcdef);
        if (facts->extraction_result) {
            pk_c_lift_result_add_diagnostic(facts->extraction_result,
                "{\"message\":\"regex compile failed: call sites\"}");
        }
        return facts;
    }

    const char *lines_start[65536];
    int lines_len[65536];
    int n_lines = 0;
    const char *p = source;
    while (*p && n_lines < 65536) {
        lines_start[n_lines] = p;
        const char *eol = strchr(p, '\n');
        if (!eol) {
            lines_len[n_lines++] = (int)strlen(p);
            break;
        }
        lines_len[n_lines++] = (int)(eol - p);
        p = eol + 1;
    }

    char current_fn[256] = "";
    int brace_depth = 0;
    int annotate_next = 0;

    for (int i = 0; i < n_lines; i++) {
        char line[4096];
        int len = lines_len[i];
        if (len >= (int)sizeof(line)) len = (int)sizeof(line) - 1;
        memcpy(line, lines_start[i], (size_t)len);
        line[len] = '\0';

        if (is_contract_annotation(line)) {
            annotate_next = 1;
            continue;
        }

        regmatch_t m[3];
        if (regexec(&re_funcdef, line, 3, m, 0) == 0 && m[1].rm_so >= 0) {
            int nlen = (int)(m[1].rm_eo - m[1].rm_so);
            if (nlen > 255) nlen = 255;
            char fname[256];
            memcpy(fname, line + m[1].rm_so, (size_t)nlen);
            fname[nlen] = '\0';

            if (!is_keyword(fname)) {
                int opens_body = strchr(line, '{') != NULL ||
                    line_opens_allman_body(lines_start, lines_len, n_lines, i);
                append_function(
                    facts,
                    path,
                    fname,
                    i + 1,
                    (int)m[1].rm_so + 1,
                    opens_body,
                    annotate_next);
                annotate_next = 0;
                if (opens_body) snprintf(current_fn, sizeof(current_fn), "%s", fname);
            }
        } else if (annotate_next && !is_blank_line(line)) {
            annotate_next = 0;
        }

        if (current_fn[0] != '\0') {
            const char *scan = line;
            regmatch_t cm[2];
            while (regexec(&re_callsite, scan, 2, cm, 0) == 0 && cm[1].rm_so >= 0) {
                int clen = (int)(cm[1].rm_eo - cm[1].rm_so);
                if (clen > 255) clen = 255;
                char callee[256];
                memcpy(callee, scan + cm[1].rm_so, (size_t)clen);
                callee[clen] = '\0';

                int column = (int)(scan - line) + (int)cm[1].rm_so + 1;
                if (!is_keyword(callee) && strcmp(callee, current_fn) != 0) {
                    if (is_macro_name(callee)) {
                        append_macro(facts, path, callee, current_fn, i + 1, column);
                    } else {
                        append_call_site(facts, path, current_fn, callee, i + 1, column);
                    }
                }
                scan += cm[1].rm_eo;
                if (*scan == '\0') break;
            }
        }

        int saw_close = 0;
        for (int ci = 0; line[ci]; ci++) {
            if (line[ci] == '{') {
                brace_depth++;
            } else if (line[ci] == '}') {
                saw_close = 1;
                if (brace_depth > 0) brace_depth--;
            }
        }
        if (saw_close && brace_depth == 0) current_fn[0] = '\0';
    }

    regfree(&re_funcdef);
    regfree(&re_callsite);
    return facts;
}

void pk_c_source_facts_free(pk_c_source_facts *facts) {
    if (!facts) return;
    for (size_t i = 0; i < facts->n_functions; i++) {
        free(facts->functions[i].name);
        free(facts->functions[i].locus.path);
    }
    for (size_t i = 0; i < facts->n_macro_calls; i++) {
        free(facts->macro_calls[i].name);
        free(facts->macro_calls[i].enclosing_function);
        free(facts->macro_calls[i].argument_text);
        free(facts->macro_calls[i].locus.path);
    }
    for (size_t i = 0; i < facts->n_call_sites; i++) {
        free(facts->call_sites[i].caller);
        free(facts->call_sites[i].callee);
        free(facts->call_sites[i].locus.path);
    }
    free(facts->functions);
    free(facts->macro_calls);
    free(facts->call_sites);
    pk_c_lift_result_free(facts->extraction_result);
    free(facts);
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run:

```bash
make -C implementations/c/sugar-lift-core test
```

Expected: `sugar-lift-core tests passed`.

- [ ] **Step 6: Commit**

```bash
git add implementations/c/sugar-lift-core
git commit -m "feat(c): extract reusable C source facts"
```

---

### Task 3: Structured Opacity And Refusals

**Files:**
- Modify: `implementations/c/sugar-lift-core/include/sugar/c_lift_core.h`
- Modify: `implementations/c/sugar-lift-core/src/core.c`
- Modify: `implementations/c/sugar-lift-core/tests/test_runner.c`

- [ ] **Step 1: Write the failing test**

Append this test and call it from `main`:

```c
static void test_opacity_and_refusal_are_separate(void) {
    pk_c_lift_result *r = pk_c_lift_result_new();
    pk_c_lift_result_add_opacity_entry(
        r,
        "unexpanded-macro",
        "fixture.c",
        7,
        5,
        "macro body unavailable",
        "sparse");
    pk_c_lift_result_add_refusal_entry(
        r,
        "unsupported-lock-transfer",
        "fixture.c",
        9,
        3,
        "lockdep",
        "lock released through function pointer");
    char *json = pk_c_lift_result_to_json(r);
    const char *want =
        "{\"declarations\":[],\"callEdges\":[],\"diagnostics\":[],"
        "\"opacityReport\":[{\"affectedSurface\":\"sparse\",\"kind\":\"unexpanded-macro\","
        "\"locus\":{\"column\":5,\"line\":7,\"path\":\"fixture.c\"},\"reason\":\"macro body unavailable\"}],"
        "\"refusals\":[{\"kind\":\"unsupported-lock-transfer\","
        "\"locus\":{\"column\":3,\"line\":9,\"path\":\"fixture.c\"},"
        "\"reason\":\"lock released through function pointer\",\"surface\":\"lockdep\"}]}";
    assert_eq(json, want, "opacity and refusal separation");
    free(json);
    pk_c_lift_result_free(r);
}
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
make -C implementations/c/sugar-lift-core test
```

Expected: compile failure for missing structured helper functions.

- [ ] **Step 3: Add structured helper declarations**

Add to `c_lift_core.h`:

```c
int pk_c_lift_result_add_opacity_entry(
    pk_c_lift_result *result,
    const char *kind,
    const char *path,
    int line,
    int column,
    const char *reason,
    const char *affected_surface);

int pk_c_lift_result_add_refusal_entry(
    pk_c_lift_result *result,
    const char *kind,
    const char *path,
    int line,
    int column,
    const char *surface,
    const char *reason);
```

- [ ] **Step 4: Implement structured helper functions**

In `core.c`, add JSON string escaping and the two helpers. The emitted object key order must match the test expectation:

```c
static void append_json_string(pk_c_buf *buf, const char *s) {
    buf_append(buf, "\"");
    for (const char *p = s; *p; p++) {
        unsigned char c = (unsigned char)*p;
        if (c == '"') {
            buf_append(buf, "\\\"");
        } else if (c == '\\') {
            buf_append(buf, "\\\\");
        } else if (c == '\n') {
            buf_append(buf, "\\n");
        } else if (c == '\r') {
            buf_append(buf, "\\r");
        } else if (c == '\t') {
            buf_append(buf, "\\t");
        } else {
            char one[2] = {(char)c, '\0'};
            buf_append(buf, one);
        }
    }
    buf_append(buf, "\"");
}

static void append_locus(pk_c_buf *buf, const char *path, int line, int column) {
    char nbuf[32];
    buf_append(buf, "{\"column\":");
    snprintf(nbuf, sizeof(nbuf), "%d", column);
    buf_append(buf, nbuf);
    buf_append(buf, ",\"line\":");
    snprintf(nbuf, sizeof(nbuf), "%d", line);
    buf_append(buf, nbuf);
    buf_append(buf, ",\"path\":");
    append_json_string(buf, path);
    buf_append(buf, "}");
}

int pk_c_lift_result_add_opacity_entry(
    pk_c_lift_result *result,
    const char *kind,
    const char *path,
    int line,
    int column,
    const char *reason,
    const char *affected_surface)
{
    pk_c_buf buf;
    buf_init(&buf);
    buf_append(&buf, "{\"affectedSurface\":");
    append_json_string(&buf, affected_surface);
    buf_append(&buf, ",\"kind\":");
    append_json_string(&buf, kind);
    buf_append(&buf, ",\"locus\":");
    append_locus(&buf, path, line, column);
    buf_append(&buf, ",\"reason\":");
    append_json_string(&buf, reason);
    buf_append(&buf, "}");
    int ok = pk_c_lift_result_add_opacity(result, buf.data);
    free(buf.data);
    return ok;
}

int pk_c_lift_result_add_refusal_entry(
    pk_c_lift_result *result,
    const char *kind,
    const char *path,
    int line,
    int column,
    const char *surface,
    const char *reason)
{
    pk_c_buf buf;
    buf_init(&buf);
    buf_append(&buf, "{\"kind\":");
    append_json_string(&buf, kind);
    buf_append(&buf, ",\"locus\":");
    append_locus(&buf, path, line, column);
    buf_append(&buf, ",\"reason\":");
    append_json_string(&buf, reason);
    buf_append(&buf, ",\"surface\":");
    append_json_string(&buf, surface);
    buf_append(&buf, "}");
    int ok = pk_c_lift_result_add_refusal(result, buf.data);
    free(buf.data);
    return ok;
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run:

```bash
make -C implementations/c/sugar-lift-core test
```

Expected: `sugar-lift-core tests passed`.

- [ ] **Step 6: Commit**

```bash
git add implementations/c/sugar-lift-core
git commit -m "feat(c): separate opacity and refusal streams"
```

---

### Task 4: Route `sugar-lsp-c` Through The Core

**Files:**
- Modify: `implementations/c/sugar-lsp-c/Makefile`
- Modify: `implementations/c/sugar-lsp-c/main.c`
- Modify: `implementations/c/sugar-lsp-c/tests/integration.sh`

- [ ] **Step 1: Write the failing regression assertion**

In `implementations/c/sugar-lsp-c/tests/integration.sh`, replace the old `warnings` check and shutdown check:

```sh
check "T9 parse: warnings key present" "$LINE2" '"warnings":'
check "T10 shutdown: result null" "$LINE3" '"result":null'
```

with checks for the shared core result shape:

```sh
check "T9 parse: diagnostics key present" "$LINE2" '"diagnostics":'
check "T10 parse: opacityReport key present" "$LINE2" '"opacityReport":'
check "T11 parse: refusals key present" "$LINE2" '"refusals":'
check "T12 shutdown: result null" "$LINE3" '"result":null'
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
make -C implementations/c/sugar-lsp-c test
```

Expected: failure because current `sugar-lsp-c` emits `warnings` and does not include `diagnostics`, `opacityReport`, or `refusals`.

- [ ] **Step 3: Link `sugar-lsp-c` against the core**

Modify `implementations/c/sugar-lsp-c/Makefile`:

```makefile
CC      = cc
CFLAGS  = -std=c11 -Wall -Wextra -Wpedantic -O2 -I../sugar-lift-core/include

BIN     = sugar-lsp-c
SRC     = main.c ../sugar-lift-core/src/core.c ../sugar-lift-core/src/parser.c
TEST_SH = tests/integration.sh
```

Keep the existing `all`, `test`, `install`, and `clean` targets unchanged.

- [ ] **Step 4: Delegate parse result assembly to the core**

In `main.c`, remove the local parser implementation because the core now owns it:

- Remove `#include <regex.h>`.
- Delete the block from `#define MAX_DECLS 256` through the end of `static ParseResult parse_c_source(...)`.
- Delete the final `if (regexes_compiled) { ... }` cleanup block in `main`.

Then include the core header:

```c
#include "sugar/c_lift_core.h"
```

Add this helper above `handle_parse`:

```c
static void add_contract_decl(pk_c_lift_result *result, const char *name) {
    Buf decl;
    buf_init(&decl);
    buf_append(&decl, "{\"kind\":\"contract\",\"name\":");
    json_escape_str(&decl, name);
    buf_append(&decl, ",\"outBinding\":\"out\"}");
    pk_c_lift_result_add_declaration(result, decl.data);
    buf_free(&decl);
}
```

Replace the body of `handle_parse` with:

```c
static void handle_parse(const char *id, const char *json_line) {
    char *path = json_extract_str(json_line, "path");
    char *source = json_extract_str(json_line, "source");

    if (!source) {
        free(path);
        send_error(id, -32602, "parse: missing params.source");
        return;
    }

    pk_c_source_facts *facts = pk_c_parse_source(path ? path : "lsp-document.c", source);
    free(source);
    free(path);

    pk_c_lift_result *result_obj = pk_c_lift_result_new();
    if (!result_obj) {
        pk_c_source_facts_free(facts);
        send_error(id, -32603, "parse: out of memory");
        return;
    }

    if (facts) {
        for (size_t i = 0; i < facts->n_functions; i++) {
            if (facts->functions[i].has_contract_annotation) {
                add_contract_decl(result_obj, facts->functions[i].name);
            }
        }
        if (facts->extraction_result) {
            for (size_t i = 0; i < facts->extraction_result->diagnostics.len; i++) {
                pk_c_lift_result_add_diagnostic(
                    result_obj,
                    facts->extraction_result->diagnostics.items[i]);
            }
        }
        pk_c_source_facts_free(facts);
    }

    char *result_json = pk_c_lift_result_to_json(result_obj);
    send_response(id, result_json);
    free(result_json);
    pk_c_lift_result_free(result_obj);
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run:

```bash
make -C implementations/c/sugar-lsp-c test
```

Expected: all integration checks pass, including `opacityReport` and `refusals` keys.

- [ ] **Step 6: Run the core tests again**

Run:

```bash
make -C implementations/c/sugar-lift-core test
```

Expected: `sugar-lift-core tests passed`.

- [ ] **Step 7: Commit**

```bash
git add implementations/c/sugar-lsp-c implementations/c/sugar-lift-core
git commit -m "refactor(c): route lsp parser through lift core"
```

---

### Task 5: Sparse Lifter

**Files:**
- Create: `implementations/c/sugar-lift-c-sparse/Makefile`
- Create: `implementations/c/sugar-lift-c-sparse/src/main.c`
- Create: `implementations/c/sugar-lift-c-sparse/src/sparse.c`
- Create: `implementations/c/sugar-lift-c-sparse/tests/fixtures/sparse_basic.c`
- Create: `implementations/c/sugar-lift-c-sparse/tests/integration.sh`
- Create: `implementations/c/.sugar/lift/c-sparse/manifest.toml`

- [ ] **Step 1: Write the sparse fixture and failing integration test**

Create `tests/fixtures/sparse_basic.c`:

```c
#define __user
#define __must_hold(x)

int copy_name(char __user *buf, int len)
{
    return len;
}

void update_locked(int *state) __must_hold(lock)
{
    *state = 1;
}
```

Create `tests/integration.sh`:

```sh
#!/bin/sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN="$SCRIPT_DIR/../sugar-lift-c-sparse"
FIXTURE="$SCRIPT_DIR/fixtures/sparse_basic.c"

if [ ! -x "$BIN" ]; then
    echo "FAIL: binary not found: $BIN" >&2
    exit 1
fi

SOURCE=$(sed 's/\\/\\\\/g; s/"/\\"/g; s/$/\\n/' "$FIXTURE" | tr -d '\n' | sed 's/\\n$//')
REQUEST="{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"parse\",\"params\":{\"path\":\"sparse_basic.c\",\"source\":\"$SOURCE\"}}"
RESPONSE=$(printf '%s\n' "$REQUEST" | "$BIN" --rpc)

printf '%s\n' "$RESPONSE" | grep -q '"name":"c-sparse.user-pointer"' || {
    echo "FAIL: missing __user contract" >&2
    echo "$RESPONSE" >&2
    exit 1
}

printf '%s\n' "$RESPONSE" | grep -q '"name":"c-sparse.must-hold"' || {
    echo "FAIL: missing __must_hold contract" >&2
    echo "$RESPONSE" >&2
    exit 1
}

printf '%s\n' "$RESPONSE" | grep -q '"opacityReport":\[\]' || {
    echo "FAIL: sparse fixture should have empty opacity report" >&2
    echo "$RESPONSE" >&2
    exit 1
}

printf 'sugar-lift-c-sparse integration passed\n'
```

- [ ] **Step 2: Add the Makefile and manifest**

Create `Makefile`:

```makefile
# SPDX-License-Identifier: MIT OR Apache-2.0

CC = cc
CFLAGS = -Wall -Wextra -Wpedantic -std=c11 -I../sugar-lift-core/include -g

BIN = sugar-lift-c-sparse
SRC = src/main.c src/sparse.c ../sugar-lift-core/src/core.c ../sugar-lift-core/src/parser.c
TEST_SH = tests/integration.sh

.PHONY: all test clean

all: $(BIN)

$(BIN): $(SRC)
	$(CC) $(CFLAGS) -o $@ $(SRC)

test: $(BIN) $(TEST_SH)
	@chmod +x $(TEST_SH)
	@$(TEST_SH)

clean:
	rm -f $(BIN)
```

Create `implementations/c/.sugar/lift/c-sparse/manifest.toml`:

```toml
name = "c-sparse"
version = "0.1.0"
protocol_version = "sugar-lift/1"
command = ["./sugar-lift-c-sparse/sugar-lift-c-sparse", "--rpc"]
working_dir = "."

[capabilities]
authoring_surfaces = ["c-sparse"]
ir_version = "v1.1.0"
emits_signed_mementos = false
```

- [ ] **Step 3: Run the test to verify it fails**

Run:

```bash
make -C implementations/c/sugar-lift-c-sparse test
```

Expected: compile failure because `src/main.c` and `src/sparse.c` do not exist.

- [ ] **Step 4: Implement sparse lifter entrypoint**

Create `src/main.c`:

```c
/* SPDX-License-Identifier: MIT OR Apache-2.0 */
#define _GNU_SOURCE
#include "sugar/c_lift_core.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

pk_c_lift_result *pk_c_sparse_lift_source(const char *path, const char *source);

static char *extract_string_field(const char *json, const char *field) {
    char needle[128];
    snprintf(needle, sizeof(needle), "\"%s\"", field);
    const char *p = strstr(json, needle);
    if (!p) return NULL;
    p += strlen(needle);
    while (*p == ':' || *p == ' ' || *p == '\t') p++;
    if (*p != '"') return NULL;
    p++;
    size_t cap = strlen(p) + 1;
    char *out = (char *)malloc(cap);
    size_t len = 0;
    while (*p && *p != '"') {
        if (*p == '\\' && p[1]) {
            p++;
            if (*p == 'n') out[len++] = '\n';
            else if (*p == 't') out[len++] = '\t';
            else out[len++] = *p;
        } else {
            out[len++] = *p;
        }
        p++;
    }
    out[len] = '\0';
    return out;
}

int main(int argc, char **argv) {
    int rpc = 0;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--rpc") == 0) rpc = 1;
    }
    if (!rpc) {
        fprintf(stderr, "Usage: sugar-lift-c-sparse --rpc\n");
        return 1;
    }

    char *line = NULL;
    size_t cap = 0;
    while (getline(&line, &cap, stdin) != -1) {
        char *path = extract_string_field(line, "path");
        char *source = extract_string_field(line, "source");
        if (!source) {
            printf("{\"jsonrpc\":\"2.0\",\"id\":1,\"error\":{\"code\":-32602,\"message\":\"missing source\"}}\n");
            fflush(stdout);
            free(path);
            continue;
        }
        pk_c_lift_result *result = pk_c_sparse_lift_source(path ? path : "source.c", source);
        char *json = pk_c_lift_result_to_json(result);
        printf("{\"jsonrpc\":\"2.0\",\"id\":1,\"result\":%s}\n", json);
        fflush(stdout);
        free(json);
        pk_c_lift_result_free(result);
        free(path);
        free(source);
    }
    free(line);
    return 0;
}
```

- [ ] **Step 5: Implement minimal sparse extraction**

Create `src/sparse.c`:

```c
/* SPDX-License-Identifier: MIT OR Apache-2.0 */
#include "sugar/c_lift_core.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void add_contract(pk_c_lift_result *result, const char *name, const char *symbol) {
    char json[512];
    snprintf(json, sizeof(json),
             "{\"kind\":\"contract\",\"name\":\"%s\",\"outBinding\":\"out\","
             "\"post\":{\"args\":[{\"kind\":\"var\",\"name\":\"%s\"}],"
             "\"kind\":\"atomic\",\"name\":\"%s\"}}",
             name, symbol, name);
    pk_c_lift_result_add_declaration(result, json);
}

pk_c_lift_result *pk_c_sparse_lift_source(const char *path, const char *source) {
    pk_c_lift_result *result = pk_c_lift_result_new();
    pk_c_source_facts *facts = pk_c_parse_source(path, source);
    if (!facts) return result;

    if (strstr(source, "__user")) {
        add_contract(result, "c-sparse.user-pointer", "ptr");
    }
    if (strstr(source, "__rcu")) {
        add_contract(result, "c-sparse.rcu-pointer", "ptr");
    }
    if (strstr(source, "__must_hold")) {
        add_contract(result, "c-sparse.must-hold", "lock");
    }
    if (strstr(source, "__acquires")) {
        add_contract(result, "c-sparse.acquires", "lock");
    }
    if (strstr(source, "__releases")) {
        add_contract(result, "c-sparse.releases", "lock");
    }

    pk_c_source_facts_free(facts);
    return result;
}
```

- [ ] **Step 6: Run the test to verify it passes**

Run:

```bash
make -C implementations/c/sugar-lift-c-sparse test
```

Expected: `sugar-lift-c-sparse integration passed`.

- [ ] **Step 7: Commit**

```bash
git add implementations/c/sugar-lift-c-sparse implementations/c/.sugar/lift/c-sparse
git commit -m "feat(c): add sparse contract lifter"
```

---

### Task 6: Assertions Lifter

**Files:**
- Create: `implementations/c/sugar-lift-c-assertions/Makefile`
- Create: `implementations/c/sugar-lift-c-assertions/src/main.c`
- Create: `implementations/c/sugar-lift-c-assertions/src/assertions.c`
- Create: `implementations/c/sugar-lift-c-assertions/tests/fixtures/assertions_basic.c`
- Create: `implementations/c/sugar-lift-c-assertions/tests/integration.sh`
- Create: `implementations/c/.sugar/lift/c-assertions/manifest.toml`

- [ ] **Step 1: Write the fixture and failing integration test**

Create `tests/fixtures/assertions_basic.c`:

```c
void check_value(int value)
{
    WARN_ON(value < 0);
    BUILD_BUG_ON(sizeof(int) < 4);
}
```

Create `tests/integration.sh`:

```sh
#!/bin/sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN="$SCRIPT_DIR/../sugar-lift-c-assertions"
FIXTURE="$SCRIPT_DIR/fixtures/assertions_basic.c"

if [ ! -x "$BIN" ]; then
    echo "FAIL: binary not found: $BIN" >&2
    exit 1
fi

SOURCE=$(sed 's/\\/\\\\/g; s/"/\\"/g; s/$/\\n/' "$FIXTURE" | tr -d '\n' | sed 's/\\n$//')
REQUEST="{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"parse\",\"params\":{\"path\":\"assertions_basic.c\",\"source\":\"$SOURCE\"}}"
RESPONSE=$(printf '%s\n' "$REQUEST" | "$BIN" --rpc)

printf '%s\n' "$RESPONSE" | grep -q '"name":"c-assertions.warn-on"' || {
    echo "FAIL: missing WARN_ON witness" >&2
    echo "$RESPONSE" >&2
    exit 1
}

printf '%s\n' "$RESPONSE" | grep -q '"name":"c-assertions.build-bug-on"' || {
    echo "FAIL: missing BUILD_BUG_ON witness" >&2
    echo "$RESPONSE" >&2
    exit 1
}

printf 'sugar-lift-c-assertions integration passed\n'
```

- [ ] **Step 2: Add Makefile and manifest**

Create `Makefile`:

```makefile
# SPDX-License-Identifier: MIT OR Apache-2.0

CC = cc
CFLAGS = -Wall -Wextra -Wpedantic -std=c11 -I../sugar-lift-core/include -g

BIN = sugar-lift-c-assertions
SRC = src/main.c src/assertions.c ../sugar-lift-core/src/core.c ../sugar-lift-core/src/parser.c
TEST_SH = tests/integration.sh

.PHONY: all test clean

all: $(BIN)

$(BIN): $(SRC)
	$(CC) $(CFLAGS) -o $@ $(SRC)

test: $(BIN) $(TEST_SH)
	@chmod +x $(TEST_SH)
	@$(TEST_SH)

clean:
	rm -f $(BIN)
```

Create `implementations/c/.sugar/lift/c-assertions/manifest.toml`:

```toml
name = "c-assertions"
version = "0.1.0"
protocol_version = "sugar-lift/1"
command = ["./sugar-lift-c-assertions/sugar-lift-c-assertions", "--rpc"]
working_dir = "."

[capabilities]
authoring_surfaces = ["c-assertions"]
ir_version = "v1.1.0"
emits_signed_mementos = false
```

- [ ] **Step 3: Run the test to verify it fails**

Run:

```bash
make -C implementations/c/sugar-lift-c-assertions test
```

Expected: compile failure because source files do not exist.

- [ ] **Step 4: Implement the assertions lifter entrypoint**

Create `src/main.c`:

```c
/* SPDX-License-Identifier: MIT OR Apache-2.0 */
#define _GNU_SOURCE
#include "sugar/c_lift_core.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

pk_c_lift_result *pk_c_assertions_lift_source(const char *path, const char *source);

static char *extract_string_field(const char *json, const char *field) {
    char needle[128];
    snprintf(needle, sizeof(needle), "\"%s\"", field);
    const char *p = strstr(json, needle);
    if (!p) return NULL;
    p += strlen(needle);
    while (*p == ':' || *p == ' ' || *p == '\t') p++;
    if (*p != '"') return NULL;
    p++;
    size_t cap = strlen(p) + 1;
    char *out = (char *)malloc(cap);
    size_t len = 0;
    while (*p && *p != '"') {
        if (*p == '\\' && p[1]) {
            p++;
            if (*p == 'n') out[len++] = '\n';
            else if (*p == 't') out[len++] = '\t';
            else out[len++] = *p;
        } else {
            out[len++] = *p;
        }
        p++;
    }
    out[len] = '\0';
    return out;
}

int main(int argc, char **argv) {
    int rpc = 0;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--rpc") == 0) rpc = 1;
    }
    if (!rpc) {
        fprintf(stderr, "Usage: sugar-lift-c-assertions --rpc\n");
        return 1;
    }

    char *line = NULL;
    size_t cap = 0;
    while (getline(&line, &cap, stdin) != -1) {
        char *path = extract_string_field(line, "path");
        char *source = extract_string_field(line, "source");
        if (!source) {
            printf("{\"jsonrpc\":\"2.0\",\"id\":1,\"error\":{\"code\":-32602,\"message\":\"missing source\"}}\n");
            fflush(stdout);
            free(path);
            continue;
        }
        pk_c_lift_result *result = pk_c_assertions_lift_source(path ? path : "source.c", source);
        char *json = pk_c_lift_result_to_json(result);
        printf("{\"jsonrpc\":\"2.0\",\"id\":1,\"result\":%s}\n", json);
        fflush(stdout);
        free(json);
        pk_c_lift_result_free(result);
        free(path);
        free(source);
    }
    free(line);
    return 0;
}
```

- [ ] **Step 5: Implement minimal assertions extraction**

Create `src/assertions.c`:

```c
/* SPDX-License-Identifier: MIT OR Apache-2.0 */
#include "sugar/c_lift_core.h"
#include <stdio.h>
#include <string.h>

static void add_witness(pk_c_lift_result *result, const char *name) {
    char json[512];
    snprintf(json, sizeof(json),
             "{\"kind\":\"contract\",\"name\":\"%s\",\"outBinding\":\"out\","
             "\"post\":{\"args\":[],\"kind\":\"atomic\",\"name\":\"%s\"}}",
             name, name);
    pk_c_lift_result_add_declaration(result, json);
}

pk_c_lift_result *pk_c_assertions_lift_source(const char *path, const char *source) {
    pk_c_lift_result *result = pk_c_lift_result_new();
    pk_c_source_facts *facts = pk_c_parse_source(path, source);
    if (!facts) return result;

    if (strstr(source, "WARN_ON(") || strstr(source, "WARN_ON_ONCE(")) {
        add_witness(result, "c-assertions.warn-on");
    }
    if (strstr(source, "BUILD_BUG_ON(")) {
        add_witness(result, "c-assertions.build-bug-on");
    }
    if (strstr(source, "BUG_ON(")) {
        add_witness(result, "c-assertions.bug-on");
    }
    if (strstr(source, "assert(")) {
        add_witness(result, "c-assertions.assert");
    }

    pk_c_source_facts_free(facts);
    return result;
}
```

- [ ] **Step 6: Run the test to verify it passes**

Run:

```bash
make -C implementations/c/sugar-lift-c-assertions test
```

Expected: `sugar-lift-c-assertions integration passed`.

- [ ] **Step 7: Commit**

```bash
git add implementations/c/sugar-lift-c-assertions implementations/c/.sugar/lift/c-assertions
git commit -m "feat(c): add assertions contract lifter"
```

---

### Task 7: Composition Fixture

**Files:**
- Create: `implementations/c/sugar-lift-composition/Makefile`
- Create: `implementations/c/sugar-lift-composition/tests/fixtures/sparse_and_assertions.c`
- Create: `implementations/c/sugar-lift-composition/tests/integration.sh`

- [ ] **Step 1: Write the composition fixture**

Create `tests/fixtures/sparse_and_assertions.c`:

```c
#define __user

int load_user_value(int __user *ptr)
{
    WARN_ON(!ptr);
    return ptr ? *ptr : -14;
}
```

- [ ] **Step 2: Write the failing integration test**

Create `tests/integration.sh`:

```sh
#!/bin/sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$SCRIPT_DIR/../.."
FIXTURE="$SCRIPT_DIR/fixtures/sparse_and_assertions.c"
SPARSE="$ROOT/sugar-lift-c-sparse/sugar-lift-c-sparse"
ASSERTIONS="$ROOT/sugar-lift-c-assertions/sugar-lift-c-assertions"

SOURCE=$(sed 's/\\/\\\\/g; s/"/\\"/g; s/$/\\n/' "$FIXTURE" | tr -d '\n' | sed 's/\\n$//')
REQUEST="{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"parse\",\"params\":{\"path\":\"sparse_and_assertions.c\",\"source\":\"$SOURCE\"}}"

SPARSE_RESPONSE=$(printf '%s\n' "$REQUEST" | "$SPARSE" --rpc)
ASSERT_RESPONSE=$(printf '%s\n' "$REQUEST" | "$ASSERTIONS" --rpc)

printf '%s\n' "$SPARSE_RESPONSE" | grep -q '"name":"c-sparse.user-pointer"' || {
    echo "FAIL: sparse lifter did not emit __user contract" >&2
    echo "$SPARSE_RESPONSE" >&2
    exit 1
}

printf '%s\n' "$ASSERT_RESPONSE" | grep -q '"name":"c-assertions.warn-on"' || {
    echo "FAIL: assertions lifter did not emit WARN_ON witness" >&2
    echo "$ASSERT_RESPONSE" >&2
    exit 1
}

printf '%s\n' "$SPARSE_RESPONSE" | grep -q '"refusals":\[\]' || {
    echo "FAIL: sparse refusals should stay empty" >&2
    exit 1
}

printf '%s\n' "$ASSERT_RESPONSE" | grep -q '"opacityReport":\[\]' || {
    echo "FAIL: assertions opacity should stay empty" >&2
    exit 1
}

printf 'C lifter composition integration passed\n'
```

- [ ] **Step 3: Add composition Makefile**

Create `Makefile`:

```makefile
# SPDX-License-Identifier: MIT OR Apache-2.0

.PHONY: all test clean

all: test

test:
	$(MAKE) -C ../sugar-lift-c-sparse all
	$(MAKE) -C ../sugar-lift-c-assertions all
	@chmod +x tests/integration.sh
	@tests/integration.sh

clean:
	$(MAKE) -C ../sugar-lift-c-sparse clean
	$(MAKE) -C ../sugar-lift-c-assertions clean
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
make -C implementations/c/sugar-lift-composition test
```

Expected: `C lifter composition integration passed`.

- [ ] **Step 5: Commit**

```bash
git add implementations/c/sugar-lift-composition
git commit -m "test(c): add lifter composition fixture"
```

---

### Task 8: Top-Level Build And Test Wiring

**Files:**
- Modify: `Makefile`

- [ ] **Step 1: Write the failing aggregate expectation**

Run the current aggregate before editing:

```bash
make build-c
make test-c
```

Expected: passes existing C packages but does not build or test `sugar-lift-core`, `sugar-lift-c-sparse`, `sugar-lift-c-assertions`, or `sugar-lift-composition`.

- [ ] **Step 2: Update `build-c`**

Replace the `make build-c` help text with:

```makefile
	@echo "  make build-c        cc build of C IR, lift core, C lifters, LSP, and self-contract library"
```

Modify the top-level `build-c` target:

```makefile
.PHONY: build-c
build-c:
	$(MAKE) -C implementations/c/sugar-ir all
	$(MAKE) -C implementations/c/sugar-lift-core all
	$(MAKE) -C implementations/c/sugar-lift-c-sparse all
	$(MAKE) -C implementations/c/sugar-lift-c-assertions all
	$(MAKE) -C implementations/c/sugar-lsp-c all
	$(MAKE) -C implementations/c/sugar-self-contracts lib
```

- [ ] **Step 3: Update `test-c`**

Modify the top-level `test-c` target:

```makefile
.PHONY: test-c
test-c: build-c
	$(MAKE) -C implementations/c/sugar-ir test
	$(MAKE) -C implementations/c/sugar-lift-core test
	$(MAKE) -C implementations/c/sugar-lift-c-sparse test
	$(MAKE) -C implementations/c/sugar-lift-c-assertions test
	$(MAKE) -C implementations/c/sugar-lift-composition test
	$(MAKE) -C implementations/c/sugar-lsp-c test
	$(MAKE) -C implementations/c/sugar-self-contracts test
```

- [ ] **Step 4: Run the aggregate to verify it passes**

Run:

```bash
make test-c
```

Expected: all existing and new C tests pass.

- [ ] **Step 5: Run status check**

Run:

```bash
git status --short
```

Expected: only planned implementation files are modified.

- [ ] **Step 6: Commit**

```bash
git add Makefile
git commit -m "build(c): wire c lifter family tests"
```

---

## Final Verification

Run:

```bash
make test-c
git status --short
```

Expected:

- `make test-c` exits 0.
- `git status --short` shows no uncommitted implementation changes except intentional follow-up docs if any were added after the final commit.

If time permits, also run:

```bash
make build-c
make -C implementations/c/sugar-lsp-c test
```

Expected: both exit 0.
