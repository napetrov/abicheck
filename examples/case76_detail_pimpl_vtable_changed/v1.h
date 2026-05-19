// case76 v1 — public class inherits from a detail:: polymorphic base.
//
// Public consumers call virtual methods through the public class. The
// vtable layout is determined by the detail:: base. Adding a virtual
// method to the detail:: base reshuffles the vtable, breaking already-
// compiled callers that dispatch by index.
#pragma once

namespace mylib {
namespace detail {

class algorithm_iface {
public:
    virtual ~algorithm_iface() = default;
    virtual int run() = 0;
    virtual int status() const = 0;
};

} // namespace detail

class svm_algorithm : public detail::algorithm_iface {
public:
    svm_algorithm();
    int run() override;
    int status() const override;
private:
    int state_;
};

extern "C" detail::algorithm_iface* mylib_make_svm();
extern "C" void mylib_free_algo(detail::algorithm_iface*);

} // namespace mylib
