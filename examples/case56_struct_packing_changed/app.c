#include <stdio.h>

/* App compiled against v1 layout (natural alignment, sizeof=12) */
typedef struct {
    char  tag;
    int   value;    /* offset 4 */
    char  status;
} Record;

extern Record* record_create(char tag, int value, char status);
extern void record_destroy(Record *r);
extern int record_get_value(const Record *r);

int main(void) {
    Record *r = record_create('A', 42, 'X');
    printf("value = %d\n", record_get_value(r));
    /* v1: value at offset 4, reads correctly = 42 */
    /* v2: value at offset 1 (packed), offset mismatch → garbage */
    record_destroy(r);
    return 0;
}
