#include <stdexcept>
extern "C" void ext_reset() {  // Note: NO noexcept here
    throw std::runtime_error("thrown from ext");
}
