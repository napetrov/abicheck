/* case44: Cyclic type — member added to a self-referential struct
 *
 * A linked-list node gains a new data member. The struct is self-referential
 * (next pointer). All callers that allocate / memcpy / pass by value break.
 *
 * BREAKING: TYPE_SIZE_CHANGED (sizeof(Node) grows)
 * libabigail equivalent: Added_Non_Virtual_Member_Variable (in cyclic type)
 */
#ifndef CASE44_V1_H
#define CASE44_V1_H

typedef struct Node {
    int data;
    struct Node *next;
} Node;

Node *node_create(int data);
void  node_free(Node *n);
int   node_data(const Node *n);

#endif
