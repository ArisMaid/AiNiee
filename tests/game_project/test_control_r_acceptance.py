"""Audited ignored R stays preserved, never silently repaired to CR."""
from pathlib import Path

from ModuleFolders.Domain.GameProject.TokenPolicy import TokenPolicy
from ModuleFolders.Infrastructure.GameAdapters.RpgMaker.ProfileLoader import load_profile


def test_profile_declares_r_only_with_current_consumer_fingerprints():
    profile=load_profile(Path(__file__).resolve().parents[2]/'Resource/GameProfiles/selenoxia-test-0.141.yaml')
    assert 'R' in profile['token_commands']
    for name in ['js/rmmz_windows.js','js/plugins/selenoxia/KdCommon.js','js/plugins/EscapeCharacterSe.js',
            'js/plugins/FontLoad.js','js/plugins/DarkPlasma_TextLog.js','js/plugins/DTextPicture.js']:
        assert len(profile['match']['fingerprints'][name])==64
    policy=TokenPolicy(profile['token_commands'],literal_tokens=profile['token_literals'])
    source=r'\C[9]Alpha\R';tokens,issues=policy.scan(source)
    assert not issues and [t.raw for t in tokens]==[r'\C[9]',r'\R']
    assert not policy.validate(source,r'\C[9]中文\R')
    assert policy.validate(source,r'\C[9]中文')
    assert policy.validate(source,r'\C[9]中文\CR')
    assert TokenPolicy().scan(source)[1]
    protected=policy.protect(source)
    text,issues=protected.restore(protected.text.replace('Alpha','中文'))
    assert text==r'\C[9]中文\R' and not issues
