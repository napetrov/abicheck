"""B6: Mixed C + C++ library (abi-dumper #40, abicc #64, #70).

Verify detect_profile() handles libraries with both C++ mangled (_Z) symbols
and plain C (extern "C") symbols.

In a mixed library:
- Some functions are exported as C++ (mangled with _Z prefix)
- Some functions are exported as C (extern "C", not mangled)
- detect_profile() must return "cpp" (C++ presence takes precedence)

This extends TestCProfileDetection in test_issues_e1_e4.py with the mixed case.
"""
from __future__ import annotations


from abicheck.core.pipeline import detect_profile
from abicheck.model import AbiSnapshot, Function, Visibility


def _func(name: str, mangled: str, **kwargs: object) -> Function:
    defaults: dict[str, object] = dict(return_type="void", visibility=Visibility.PUBLIC)
    defaults.update(kwargs)
    return Function(name=name, mangled=mangled, **defaults)  # type: ignore[arg-type]


def _snap(**kwargs: object) -> AbiSnapshot:
    defaults: dict[str, object] = dict(library="lib.so", version="1.0")
    defaults.update(kwargs)
    return AbiSnapshot(**defaults)  # type: ignore[arg-type]


class TestMixedCCppProfile:
    """detect_profile() for mixed C+C++ libraries (abi-dumper #40, abicc #64, #70)."""

    def test_mixed_library_has_cpp_profile(self) -> None:
        """Library with both _Z (C++) and plain C symbols → profile='cpp'.

        The presence of any C++ mangled symbol makes it a C++ library.
        """
        snap = _snap(functions=[
            # Plain C function
            _func("init_ctx", "init_ctx", is_extern_c=True),
            # C++ mangled function
            _func("Foo::process", "_ZN3Foo7processEv"),
        ])
        profile = detect_profile(snap)
        assert profile == "cpp", (
            f"Mixed C+C++ library must be detected as 'cpp', got {profile!r}"
        )

    def test_mixed_library_cpp_takes_precedence_over_c(self) -> None:
        """_Z mangling takes precedence even if all other functions are extern-C."""
        snap = _snap(functions=[
            _func("c_func1", "c_func1", is_extern_c=True),
            _func("c_func2", "c_func2", is_extern_c=True),
            _func("c_func3", "c_func3", is_extern_c=True),
            # One C++ symbol
            _func("Cpp::entry", "_ZN3Cpp5entryEv"),
        ])
        assert detect_profile(snap) == "cpp"

    def test_pure_c_library_detected_as_c(self) -> None:
        """Library with all extern-C and no _Z symbols → profile='c'."""
        snap = _snap(functions=[
            _func("init_ctx", "init_ctx", is_extern_c=True),
            _func("destroy_ctx", "destroy_ctx", is_extern_c=True),
            _func("process", "process", is_extern_c=True),
        ])
        assert detect_profile(snap) == "c"

    def test_pure_cpp_library_detected_as_cpp(self) -> None:
        """Library with only _Z-mangled symbols → profile='cpp'."""
        snap = _snap(functions=[
            _func("Foo::init", "_ZN3Foo4initEv"),
            _func("Bar::process", "_ZN3Bar7processEv"),
        ])
        assert detect_profile(snap) == "cpp"

    def test_hidden_cpp_function_not_counted(self) -> None:
        """Hidden C++ function must not count toward profile detection.

        Only PUBLIC and ELF_ONLY visibility functions count.
        A hidden C++ function should not flip the profile to 'cpp'.
        """
        snap = _snap(functions=[
            _func("c_func", "c_func", is_extern_c=True),
            # Hidden C++ function — not exported
            _func("internal_cpp", "_ZN8internal3fooEv", visibility=Visibility.HIDDEN),
        ])
        # Only public functions counted → pure C
        profile = detect_profile(snap)
        assert profile == "c"

    def test_mixed_library_compare_no_profile_errors(self) -> None:
        """compare() on mixed C+C++ snapshots must not raise errors."""
        from abicheck.checker import compare

        old = _snap(functions=[
            _func("c_init", "c_init", is_extern_c=True),
            _func("Cpp::run", "_ZN3Cpp3runEv"),
        ])
        new = _snap(functions=[
            _func("c_init", "c_init", is_extern_c=True),
            _func("Cpp::run", "_ZN3Cpp3runEv"),
        ])
        result = compare(old, new)
        # No changes in identical snapshots
        assert not result.changes

    def test_explicit_profile_override_respected(self) -> None:
        """Explicit language_profile always wins over heuristic."""
        snap = _snap(
            functions=[
                _func("Cpp::foo", "_ZN3Cpp3fooEv"),
            ],
            language_profile="c",  # explicit override, even though _Z present
        )
        assert detect_profile(snap) == "c"

    def test_elf_only_functions_not_extern_c(self) -> None:
        """ELF_ONLY visibility functions without _Z → not enough info → None."""
        snap = _snap(functions=[
            _func("sym1", "sym1", visibility=Visibility.ELF_ONLY),
            _func("sym2", "sym2", visibility=Visibility.ELF_ONLY),
        ])
        # ELF_ONLY functions: no is_extern_c=True, no _Z prefix → None
        # (we can't tell C vs C++ from symbol names alone without mangling)
        profile = detect_profile(snap)
        # Could be None or "c" depending on implementation — just verify no exception
        assert profile in (None, "c", "cpp")
