from snowth_my_net.collect.check import secret_warnings
from snowth_my_net.config.loader import ResolvedCredential
from snowth_my_net.config.schema import CredentialCfg
from snowth_my_net.config.secrets import Secret


def v2c(name: str, community: str) -> ResolvedCredential:
    return ResolvedCredential(CredentialCfg(name=name, version="2c", community_file="f"),
                              community=Secret(community, "test"))


def test_weak_communities_are_reported():
    assert any("well-known default" in w for w in secret_warnings([v2c("ro", "public")]))
    assert any("well-known default" in w for w in secret_warnings([v2c("ro", "short")]))
    assert secret_warnings([v2c("ro", "a-long-random-community")]) == []


def test_a_name_containing_its_secret_is_reported():
    warnings = secret_warnings([v2c("v2c-rocommunity9", "rocommunity9")])
    assert any("contains its own secret" in w for w in warnings)
