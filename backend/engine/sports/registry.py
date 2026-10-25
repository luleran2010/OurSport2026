from collections.abc import Mapping
from types import MappingProxyType

from engine.sports.base import SportModule
from engine.sports.football import FOOTBALL
from engine.sports.futsal import FUTSAL

# Fixed at import; adding a sport means adding its module here (docs/04-engine.md).
SPORTS: Mapping[str, SportModule] = MappingProxyType({FOOTBALL.code: FOOTBALL, FUTSAL.code: FUTSAL})


class UnknownSport(KeyError):
    pass


def get_sport(code: str, sports: Mapping[str, SportModule] = SPORTS) -> SportModule:
    try:
        return sports[code]
    except KeyError:
        raise UnknownSport(code) from None
