/* YELLOW inserted at 1 — shifts GREEN and BLUE */
typedef enum { RED=0, YELLOW=1, GREEN=2, BLUE=3 } Color;
Color get_color(void) { return RED; }
Color get_signal(void) { return GREEN; }  /* returns GREEN=2 in v2 */
