/* case44 v2: extra field added to cyclic Node — BREAKING */
#ifndef CASE44_V2_H
#define CASE44_V2_H

typedef struct Node {
    int data;
    int priority;       /* NEW: added field */
    struct Node *next;
} Node;

Node *node_create(int data);
void  node_free(Node *n);
int   node_data(const Node *n);

#endif
