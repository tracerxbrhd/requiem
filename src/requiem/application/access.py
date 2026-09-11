from requiem.application.configuration import ConfigurationService
from requiem.domain.access import AccessResult, evaluate_access


class CommandAccessService:
    def __init__(self, configuration: ConfigurationService) -> None:
        self.configuration = configuration

    async def check(
        self,
        guild_id: int | None,
        module_name: str,
        command_name: str,
        member_roles: frozenset[int],
    ) -> AccessResult:
        if guild_id is None:
            return AccessResult.GUILD_REQUIRED
        module, command = await self.configuration.get_access_configuration(
            guild_id, module_name, command_name
        )
        return evaluate_access(module, command, member_roles)
