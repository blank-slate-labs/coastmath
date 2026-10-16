"""Assumption curves keep flat plateaus flat, handle uneven ages and match known cubic values."""
import pytest

from coastmath.engine.assumption_curves import catmull_rom_interpolate


def test_flat_plateau_stays_exact_for_decades():
    points=[{'x':25,'y':.10},{'x':30,'y':.10},{'x':31,'y':.02},{'x':90,'y':.02}]
    for age in range(31,91):
        assert catmull_rom_interpolate(points,age) == pytest.approx(.02,abs=1e-14)
    assert catmull_rom_interpolate(points,30.5) == pytest.approx(.06)


def test_pchip_endpoint_and_two_point_linear_value():
    assert catmull_rom_interpolate([{'x':0,'y':0},{'x':1,'y':1},{'x':2,'y':1}],.5) == pytest.approx(.6875)
    assert catmull_rom_interpolate([{'x':0,'y':0},{'x':2,'y':1}],.5) == pytest.approx(.25)
