import pytest
from nmon.models import sample_to_row, row_to_sample

def test_memory_fraction_normal(fake_sample):
    s = fake_sample(mem_used=4096.0, mem_total=8192.0)
    assert s.memory_fraction == pytest.approx(0.5)

def test_memory_fraction_zero_total(fake_sample):
    s = fake_sample(mem_used=0.0, mem_total=0.0)
    assert s.memory_fraction == 0.0

def test_sample_to_row_roundtrip(fake_sample):
    s = fake_sample()
    assert row_to_sample(sample_to_row(s)) == s
