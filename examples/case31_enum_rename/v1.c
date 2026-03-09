#include "v1.h"
static log_level_t current = LOG_NONE;
void set_log_level(log_level_t level) { current = level; }
