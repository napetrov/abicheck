# ABI Breaking Cases Catalog (v1)

Ниже — систематизация кейсов из `examples/case01..case18` для исследования сценариев **ломания обратной совместимости ABI**.

## 1) Symbol/API surface breaks

1. **case01_symbol_removal** — удаление публичного символа из `.so`.
   - Риск: runtime loader error/undefined symbol.
   - Тип: hard break.

2. **case02_param_type_change** — изменение типа аргумента функции.
   - Риск: ABI mismatch по calling convention/register usage.
   - Тип: hard break.

3. **case10_return_type** — изменение типа возвращаемого значения.
   - Риск: truncation/UB на стороне потребителя.
   - Тип: hard break.

4. **case12_function_removed** — исчезновение функции (например, из-за inline-рефакторинга).
   - Риск: unresolved symbol у старых бинарей.
   - Тип: hard break.

## 2) Type/layout breaks

5. **case07_struct_layout** — изменение layout структуры (добавление поля/смещение).
   - Риск: size/offset mismatch, порча памяти.
   - Тип: hard break.

6. **case08_enum_value_change** — перестановка/вставка значений enum.
   - Риск: семантическая несовместимость (не тот branch/режим).
   - Тип: semantic ABI break.

7. **case11_global_var_type** — изменение типа глобальной переменной.
   - Риск: size/alignment mismatch.
   - Тип: hard break.

8. **case17_template_abi** — изменение layout/ABI инстанцированного template-типа.
   - Риск: binary mismatch между TU, ODR/size mismatch.
   - Тип: hard break.

9. **case18_dependency_leak** — утечка ABI зависимости через public headers.
   - Риск: внешний dependency upgrade ломает ABI без изменений в нашей `.so`.
   - Тип: transitive ABI break.

## 3) C++ ABI-specific breaks

10. **case09_cpp_vtable** — изменение порядка/набора virtual methods (vtable drift).
    - Риск: вызов не того виртуального метода.
    - Тип: hard break.

11. **case14_cpp_class_size** — изменение размера класса.
    - Риск: mismatch new/delete, object layout corruption.
    - Тип: hard break.

12. **case15_noexcept_change** — снятие `noexcept`.
    - Риск: изменение exception contract, ABI/behavioral mismatch.
    - Тип: semantic break (часто плохо детектится ELF-only).

13. **case16_inline_to_non_inline** — переход inline→non-inline (или обратно) с ODR-эффектами.
    - Риск: multiple definitions, mixed TU behavior.
    - Тип: ODR/semantic ABI risk.

## 4) ELF/linker/policy cases (важны для релизной политики)

14. **case05_soname** — отсутствует SONAME.
    - Риск: неконтролируемая подмена ABI при обновлении.
    - Тип: policy break.

15. **case06_visibility** — утечка internal symbols наружу.
    - Риск: случайный public ABI surface, future lock-in.
    - Тип: ABI hygiene break.

16. **case13_symbol_versioning** — отсутствие symbol versioning.
    - Риск: сложнее контролировать совместимость между релизами/дистрибутивами.
    - Тип: policy/tooling break.

## 5) Контрольные (не ломают ABI напрямую)

17. **case03_compat_addition** — совместимое добавление символа.
18. **case04_no_change** — baseline без изменений.

---

## Что ещё добавить в v2 (для твоего research)

1. **Calling convention drift** (`cdecl`/`stdcall`, SysV vs vectorcall).
2. **Alignment/packing changes** (`#pragma pack`, `alignas`).
3. **Bitfield layout changes** (compiler/version/flags dependent).
4. **Exception type ABI changes** (throw spec + RTTI interplay).
5. **Allocator ABI changes** (`std::pmr`, custom alloc hooks).
6. **STL ABI toggles** (`_GLIBCXX_USE_CXX11_ABI`, libc++/libstdc++ mixing).
7. **Cross-compiler ABI drift** (GCC vs Clang vs MSVC for same headers).
8. **LTO/visibility interaction** (inlined symbol disappearance with LTO).
9. **IFUNC / CPU dispatch symbol changes**.
10. **Weak symbol semantics changes**.

