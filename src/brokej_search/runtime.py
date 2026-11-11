from dataclasses import dataclass

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from brokej_search.career_profile.service import ProfileService
from brokej_search.core.config import Settings, get_settings
from brokej_search.database.base import make_engine, make_session_factory
from brokej_search.discovery.service import DiscoveryService
from brokej_search.evaluation.service import EvaluationService
from brokej_search.github.service import GitHubService


@dataclass
class Runtime:
    settings: Settings
    engine: Engine
    factory: sessionmaker[Session]
    profiles: ProfileService
    discovery: DiscoveryService
    evaluation: EvaluationService
    github: GitHubService


def create_runtime(settings: Settings | None = None) -> Runtime:
    settings = settings or get_settings()
    engine = make_engine(settings)
    factory = make_session_factory(engine)
    return Runtime(
        settings=settings,
        engine=engine,
        factory=factory,
        profiles=ProfileService(factory, settings),
        discovery=DiscoveryService(factory, settings),
        evaluation=EvaluationService(factory),
        github=GitHubService(factory),
    )
