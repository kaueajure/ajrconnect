"""Hypervisor RAM helpers for linked VMs (Docker/Podman/libvirt/VirtualBox)."""
from vm_control import GIB, MemoryStatus, bound_machine, memory_status, set_memory_limit

__all__ = ('GIB', 'MemoryStatus', 'bound_machine', 'describe', 'memory_status', 'set_memory_limit')


def describe(status):
    used = status.used_bytes / GIB
    if status.limit_bytes > 0:
        return f'{used:.2f} GiB em uso · teto da VM: {status.limit_bytes / GIB:g} GiB'
    return f'{used:.2f} GiB em uso · sem teto configurado no hipervisor'
