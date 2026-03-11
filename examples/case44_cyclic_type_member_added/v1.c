#include "v1.h"
#include <stdlib.h>
Node *node_create(int data) { Node *n = malloc(sizeof(Node)); n->data = data; n->next = 0; return n; }
void  node_free(Node *n)    { free(n); }
int   node_data(const Node *n) { return n->data; }
