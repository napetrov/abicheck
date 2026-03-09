/* case28 app: Demonstrate typedef and opaque type ABI breaks.
 *
 * Compiled against v1.h (dim_t = int, handle_t exists, Context is complete).
 * When v2 .so is swapped in (dim_t = long, handle_t removed, Context opaque),
 * the binary exhibits size mismatches and broken assumptions.
 */
#include "v1.h"
#include <stdio.h>
#include <string.h>

int main(void) {
    /* Scenario 1: dim_t size mismatch (int vs long)
     * App compiled with v1 treats dim_t as int (4 bytes).
     * v2 library returns dim_t as long (8 bytes on LP64).
     * The function signature in the .so now returns a long,
     * but the caller only reads 4 bytes worth of return value.
     */
    dim_t d = get_dimension(7);
    printf("Scenario 1 — dim_t base type change:\n");
    printf("  sizeof(dim_t) at compile time = %zu (expected 4 for int)\n", sizeof(dim_t));
    printf("  get_dimension(7) = %d\n", (int)d);
    printf("  If v2 lib loaded: dim_t is long (%zu bytes) but caller expects int (4 bytes)\n\n",
           sizeof(long));

    /* Scenario 2: handle_t typedef removed
     * App uses handle_t which exists in v1.h.
     * v2.h removes the typedef entirely — a source break.
     * At binary level, create_handle() still exists, so this works at runtime.
     */
    handle_t h = create_handle();
    printf("Scenario 2 — handle_t typedef removed:\n");
    printf("  create_handle() = %u\n", h);
    printf("  Binary still works (function exists), but recompilation against v2.h fails\n\n");

    /* Scenario 3: Context became opaque
     * With v1.h the struct is complete — we can stack-allocate and access fields.
     * With v2.h only a forward declaration is provided; sizeof/member access is impossible.
     */
    printf("Scenario 3 — struct Context became opaque:\n");
    printf("  sizeof(struct Context) at compile time = %zu\n", sizeof(struct Context));

    /* Stack-allocate Context — only possible because v1.h has the full definition */
    struct Context local;
    memset(&local, 0, sizeof(local));
    local.id = 99;
    local.flags = 0x1;
    snprintf(local.name, sizeof(local.name), "stack-ctx");
    printf("  Stack-allocated Context: id=%d flags=0x%x name=\"%s\"\n",
           local.id, local.flags, local.name);
    printf("  With v2 header this code would NOT compile (incomplete type)\n\n");

    /* Heap-allocate via library (works with both v1 and v2) */
    struct Context *ctx = context_create();
    printf("  Heap-allocated via context_create(): ptr=%p\n", (void *)ctx);
    context_destroy(ctx);

    printf("\nSummary:\n");
    printf("  - dim_t changed from int to long: SIZE MISMATCH at ABI level\n");
    printf("  - handle_t removed: SOURCE BREAK (binary still links)\n");
    printf("  - Context became opaque: SOURCE BREAK + stack alloc impossible\n");

    return 0;
}
