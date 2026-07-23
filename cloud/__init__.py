"""Plasma cloud control plane.

Owns accounts, sessions, devices, activation keys, entitlements, and update
metadata. It never runs a browser or stores browser data — see
docs/architecture/plasma-desktop-cloud/. This package is the cloud service and is
deployed separately from the desktop `manager_backend`.
"""
