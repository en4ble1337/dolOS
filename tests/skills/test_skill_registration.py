"""Tests for SkillRegistration metadata fields (Gap 2).

TDD Red phase — these tests MUST FAIL before the implementation is added.
They define the expected interface for the extended @skill decorator and
the SkillRegistration dataclass.
"""

import pytest
from skills.registry import SkillRegistry, SkillRegistration, skill


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def registry():
    """Fresh isolated registry for each test."""
    return SkillRegistry()


# ---------------------------------------------------------------------------
# SkillRegistration dataclass
# ---------------------------------------------------------------------------

class TestSkillRegistrationDataclass:
    def test_has_is_read_only_field(self):
        reg = SkillRegistration(
            name="test", description="desc", func=lambda: None
        )
        assert hasattr(reg, "is_read_only")

    def test_is_read_only_defaults_true(self):
        reg = SkillRegistration(
            name="test", description="desc", func=lambda: None
        )
        assert reg.is_read_only is True

    def test_concurrency_safe_defaults_true(self):
        reg = SkillRegistration(
            name="test", description="desc", func=lambda: None
        )
        assert reg.concurrency_safe is True

    def test_description_fn_defaults_none(self):
        reg = SkillRegistration(
            name="test", description="desc", func=lambda: None
        )
        assert reg.description_fn is None

    def test_can_set_read_only_false(self):
        reg = SkillRegistration(
            name="test", description="desc", func=lambda: None, is_read_only=False
        )
        assert reg.is_read_only is False

    def test_can_set_concurrency_safe_false(self):
        reg = SkillRegistration(
            name="test", description="desc", func=lambda: None, concurrency_safe=False
        )
        assert reg.concurrency_safe is False

    def test_description_fn_callable_accepted(self):
        fn = lambda: "dynamic description"
        reg = SkillRegistration(
            name="test", description="desc", func=lambda: None, description_fn=fn
        )
        assert reg.description_fn is fn
        assert reg.description_fn() == "dynamic description"


# ---------------------------------------------------------------------------
# SkillRegistry.get_registration
# ---------------------------------------------------------------------------

class TestRegistryGetRegistration:
    def test_get_registration_returns_skill_registration(self, registry):
        def my_skill(x: str) -> str:
            return x

        registry.register("my_skill", "A test skill", my_skill)
        reg = registry.get_registration("my_skill")
        assert isinstance(reg, SkillRegistration)

    def test_get_registration_name(self, registry):
        def my_skill(x: str) -> str:
            return x

        registry.register("my_skill", "A test skill", my_skill)
        reg = registry.get_registration("my_skill")
        assert reg.name == "my_skill"

    def test_get_registration_description(self, registry):
        def my_skill(x: str) -> str:
            return x

        registry.register("my_skill", "A test skill", my_skill)
        reg = registry.get_registration("my_skill")
        assert reg.description == "A test skill"

    def test_get_registration_func(self, registry):
        def my_skill(x: str) -> str:
            return x

        registry.register("my_skill", "A test skill", my_skill)
        reg = registry.get_registration("my_skill")
        assert reg.func is my_skill

    def test_get_registration_missing_raises_key_error(self, registry):
        with pytest.raises(KeyError):
            registry.get_registration("nonexistent")

    def test_get_registration_defaults_preserved(self, registry):
        """Default is_read_only=True when not specified."""
        def my_skill(x: str) -> str:
            return x

        registry.register("my_skill", "A test skill", my_skill)
        reg = registry.get_registration("my_skill")
        assert reg.is_read_only is True
        assert reg.concurrency_safe is True
        assert reg.description_fn is None

    def test_get_registration_stores_metadata(self, registry):
        """Metadata set via register() is preserved on the registration."""
        def my_skill(x: str) -> str:
            return x

        registry.register(
            "my_skill", "A test skill", my_skill,
            is_read_only=False, concurrency_safe=False
        )
        reg = registry.get_registration("my_skill")
        assert reg.is_read_only is False
        assert reg.concurrency_safe is False


# ---------------------------------------------------------------------------
# @skill decorator extensions
# ---------------------------------------------------------------------------

class TestSkillDecoratorMetadata:
    def test_decorator_read_only_true_by_default(self):
        local_reg = SkillRegistry()

        @skill(name="ro_skill", description="desc", registry=local_reg)
        def ro_skill(x: str) -> str:
            return x

        reg = local_reg.get_registration("ro_skill")
        assert reg.is_read_only is True

    def test_decorator_read_only_false(self):
        local_reg = SkillRegistry()

        @skill(name="mut_skill", description="desc", registry=local_reg, read_only=False)
        def mut_skill(x: str) -> str:
            return x

        reg = local_reg.get_registration("mut_skill")
        assert reg.is_read_only is False

    def test_decorator_concurrency_safe_true_by_default(self):
        local_reg = SkillRegistry()

        @skill(name="cs_skill", description="desc", registry=local_reg)
        def cs_skill(x: str) -> str:
            return x

        reg = local_reg.get_registration("cs_skill")
        assert reg.concurrency_safe is True

    def test_decorator_concurrency_safe_false(self):
        local_reg = SkillRegistry()

        @skill(name="ncs_skill", description="desc", registry=local_reg, concurrency_safe=False)
        def ncs_skill(x: str) -> str:
            return x

        reg = local_reg.get_registration("ncs_skill")
        assert reg.concurrency_safe is False

    def test_decorator_description_fn(self):
        local_reg = SkillRegistry()
        desc_fn = lambda: "computed description"

        @skill(name="dfn_skill", description="static desc", registry=local_reg, description_fn=desc_fn)
        def dfn_skill(x: str) -> str:
            return x

        reg = local_reg.get_registration("dfn_skill")
        assert reg.description_fn is desc_fn

    def test_decorator_combined_false_metadata(self):
        """Full combination: read_only=False, concurrency_safe=False."""
        local_reg = SkillRegistry()

        @skill(
            name="write_skill",
            description="writes things",
            registry=local_reg,
            read_only=False,
            concurrency_safe=False,
        )
        def write_skill(path: str, content: str) -> str:
            return f"wrote {path}"

        reg = local_reg.get_registration("write_skill")
        assert reg.is_read_only is False
        assert reg.concurrency_safe is False

    def test_get_skill_still_returns_callable(self):
        """Backwards compatibility — get_skill() still returns the function."""
        local_reg = SkillRegistry()

        @skill(name="compat_skill", description="desc", registry=local_reg)
        def compat_skill(x: str) -> str:
            return x

        fn = local_reg.get_skill("compat_skill")
        assert callable(fn)
        assert fn("hello") == "hello"
