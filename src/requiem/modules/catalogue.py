"""Known features, independent of each guild's enabled state."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModuleDefinition:
    name: str
    commands: frozenset[str]


@dataclass(frozen=True, slots=True)
class ModuleCatalogue:
    modules: tuple[ModuleDefinition, ...]

    def require_module(self, name: str) -> ModuleDefinition:
        for module in self.modules:
            if module.name == name:
                return module
        raise ValueError(f"Unknown optional module: {name}")

    def require_command(self, module_name: str, command_name: str) -> None:
        module = self.require_module(module_name)
        if command_name not in module.commands:
            raise ValueError(f"Unknown command in {module_name}: {command_name}")


CATALOGUE = ModuleCatalogue(
    modules=(
        ModuleDefinition(
            name="moderation",
            commands=frozenset({"warn", "timeout", "untimeout", "kick", "ban", "unban", "purge"}),
        ),
    ),
)
