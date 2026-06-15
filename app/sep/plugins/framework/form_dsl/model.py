# Copyright (C) 2026 Percona LLC
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Define ``AppFormModel``, the single-declaration base for model-first plugins."""

from typing import Any, ClassVar

from app.sep.plugins.framework.form_dsl.derivation import build_runtime_schema
from app.sep.plugins.framework.form_dsl.markers import FormRules
from app.sep.plugins.framework.rules import (
    apply_conditional_rules,
    ConditionalRulesModel,
)

__all__ = ["AppFormModel"]


class AppFormModel(ConditionalRulesModel):
    """Serve as the single field declaration for a model-first plugin create form.

    A subclass declares each form field once, as a Pydantic field whose
    ``Annotated[...]`` carries the DSL markers (``Ui`` plus optional ``Ref`` /
    ``Choices`` / ``Requires`` / ``Forbidden``). That one declaration drives both
    runtime validation and schema export: at class definition the conditional
    rules (field gates plus the model's ``__form_rules__``) are extracted into the
    inherited :attr:`~app.sep.plugins.framework.rules.ConditionalRulesModel.\
__conditional_rules_plan__` so the inherited validator enforces them, while
    :func:`~app.sep.plugins.framework.form_dsl.derivation.derive_form_sections`
    derives the wire schema from the same fields.

    :cvar __form_rules__: Section-scoped and plugin-scoped conditional rules that
        cannot attach to a single field (field-level gates live on the fields via
        ``Requires`` / ``Forbidden``). Defaults to an empty :class:`FormRules`.
    """

    __form_rules__: ClassVar[FormRules] = FormRules()

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        """Extract the conditional-rule plan once ``model_fields`` is populated.

        Pydantic calls this after the subclass's fields are built, so the rule
        plan can be derived from them and wired onto the class via the existing
        :func:`~app.sep.plugins.framework.rules.apply_conditional_rules` machinery.

        :param kwargs: Forwarded to the superclass hook.
        """
        super().__pydantic_init_subclass__(**kwargs)
        if not cls.model_fields:
            return
        apply_conditional_rules(build_runtime_schema(cls))(cls)
