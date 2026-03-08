# Разбор всех ABI/API кейсов из `examples/`

Ниже — практический справочник по каждому кейсу `examples/case01..case24`:

- **что именно ломает совместимость**,
- **какой риск для потребителей библиотеки**,
- **как избежать поломки**.

> Рекомендуемый формат релизной проверки: запускать кейсы как регрессионный набор и
> отдельно фиксировать в changelog, почему изменение признано совместимым/несовместимым.

## Кейсы: что ломается и как этого избежать

| Кейс | Что ломает зависимость/совместимость | Как избежать/смягчить |
|---|---|---|
| [`case01_symbol_removal`](../examples/case01_symbol_removal/README.md) | Удаление экспортируемого символа: старые бинарники получают `undefined symbol` при загрузке. | Не удалять символы в мажорной ветке; оставлять shim/обертку; депрекейтить минимум на 1 релиз. |
| [`case02_param_type_change`](../examples/case02_param_type_change/README.md) | Изменение типа параметра меняет ABI вызова (регистры/стек). | Добавлять новую функцию с новым типом, старую оставлять как совместимую обертку. |
| [`case03_compat_addition`](../examples/case03_compat_addition/README.md) | Добавление нового символа обычно совместимо, но может расширить неустойчивый API surface. | Добавлять символы с явной версионной политикой и тестом обратной совместимости. |
| [`case04_no_change`](../examples/case04_no_change/README.md) | Контрольный кейс без ABI-изменений. | Использовать как baseline в CI, чтобы ловить ложные срабатывания. |
| [`case05_soname`](../examples/case05_soname/README.md) | Некорректный SONAME ломает менеджмент зависимостей в рантайме/пакетах. | Вести строгую SONAME-политику: мажорный ABI break -> новый SONAME. |
| [`case06_visibility`](../examples/case06_visibility/README.md) | Утечка внутренних символов в экспорт: случайный публичный контракт и будущие lock-in. | `-fvisibility=hidden` по умолчанию + явные export-макросы только для публичного API. |
| [`case07_struct_layout`](../examples/case07_struct_layout/README.md) | Изменение layout структуры (size/offset/alignment) ломает старых клиентов. | Не менять публичные struct-in-place; использовать opaque handle/Pimpl; добавлять поля через versioned API. |
| [`case08_enum_value_change`](../examples/case08_enum_value_change/README.md) | Изменение числовых значений enum ломает протоколы, сериализацию и switch-логику. | Фиксировать явные значения enum; не переиспользовать старые номера; новые значения только append-style. |
| [`case09_cpp_vtable`](../examples/case09_cpp_vtable/README.md) | Изменение виртуального интерфейса меняет vtable и ломает бинарную совместимость C++. | Замораживать ABI виртуальных классов; использовать interface versioning/абстрактные адаптеры. |
| [`case10_return_type`](../examples/case10_return_type/README.md) | Изменение типа возврата меняет ABI и интерпретацию результата. | Оставлять старую функцию; вводить новую с суффиксом версии (`foo_v2`). |
| [`case11_global_var_type`](../examples/case11_global_var_type/README.md) | Смена типа глобальной переменной ломает размер/выравнивание и доступ. | Избегать публичных mutable globals; прятать состояние за getter/setter API. |
| [`case12_function_removed`](../examples/case12_function_removed/README.md) | Полное удаление функции = hard ABI break для существующих потребителей. | Сначала deprecate, затем перенос в major release с новым SONAME и миграционной заметкой. |
| [`case13_symbol_versioning`](../examples/case13_symbol_versioning/README.md) | Потеря/поломка symbol versioning ухудшает совместимость между релизами и дистрибутивами. | Поддерживать map/version script и проверять его в CI. |
| [`case14_cpp_class_size`](../examples/case14_cpp_class_size/README.md) | Изменение размера класса ломает размещение объекта и binary contract. | Для публичных C++ типов использовать Pimpl; не экспонировать layout-чувствительные поля. |
| [`case15_noexcept_change`](../examples/case15_noexcept_change/README.md) | Изменение `noexcept` меняет C++ контракт и может влиять на совместимость смешанных сборок. | `noexcept` у публичных API считать частью контракта; менять только через новую версию API. |
| [`case16_inline_to_non_inline`](../examples/case16_inline_to_non_inline/README.md) | inline↔non-inline меняет ODR/линковочное поведение между TU. | Держать стабильную стратегию инлайнинга для публичных заголовков; выносить реализацию в `.cpp`. |
| [`case17_template_abi`](../examples/case17_template_abi/README.md) | Изменение template layout/инстанцирования ломает ABI между модулями. | Минимизировать публичные template-типы в ABI; использовать type-erasure/opaque wrappers. |
| [`case18_dependency_leak`](../examples/case18_dependency_leak/README.md) | Публичный API протекает типами внешней зависимости; апдейт dependency ломает ABI без изменений в вашей `.so`. | Не экспонировать third-party типы напрямую; вводить собственные стабильные DTO/opaque handle. |
| [`case19_enum_member_removed`](../examples/case19_enum_member_removed/) | Удаление enum-элемента ломает совместимость с уже скомпилированным кодом/данными. | Не удалять старые значения; помечать deprecated и оставлять для обратной совместимости. |
| [`case20_enum_member_value_changed`](../examples/case20_enum_member_value_changed/) | Переназначение enum-значений ломает wire-format и persisted данные. | Значения enum считать неизменяемыми; для новых смыслов добавлять новые константы. |
| [`case21_method_became_static`](../examples/case21_method_became_static/) | Метод -> static меняет сигнатуру/вызов и ABI C++ класса. | Добавить новый static-метод с другим именем; старый оставить совместимым адаптером. |
| [`case22_method_const_changed`](../examples/case22_method_const_changed/) | Изменение `const`-квалификатора метода меняет mangling/overload set. | Не менять const-контракт публичных методов; вводить новую перегрузку/имя. |
| [`case23_pure_virtual_added`](../examples/case23_pure_virtual_added/) | Добавление pure virtual метода ломает всех наследников и vtable. | Добавлять методы через новую версию интерфейса (`IFoo2`), оставляя старый интерфейс неизменным. |
| [`case24_union_field_removed`](../examples/case24_union_field_removed/) | Удаление поля union меняет допустимые представления данных и ABI-контракт. | Union в публичном API фиксировать; расширять через новый versioned тип/обертку. |

## Общие правила, чтобы не ломать ABI

1. Любое изменение сигнатуры/типа в публичном API считать потенциально **breaking**.
2. Для C++ ABI использовать **Pimpl/opaque handle** как основной стабилизирующий паттерн.
3. Стабилизировать экспорт: visibility policy + symbol version script + SONAME discipline.
4. Изменения делать через **versioned API**, а не inplace-редактирование старых контрактов.
5. Держать регрессионный набор из `examples/` и проверять его в CI на каждом релизном кандидате.
