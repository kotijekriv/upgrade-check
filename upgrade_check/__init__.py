"""Upgrade Check. Copyright 2026 Attempts. GPL-3.0-or-later."""


def classFactory(iface):
    from .plugin import UpgradeCheck
    return UpgradeCheck(iface)
