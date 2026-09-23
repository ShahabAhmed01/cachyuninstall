#!/bin/bash
# Package-certification cycle (temp harness): rebuild with the .install fix,
# verify pycache/daemon behavior, self-uninstall audit, reinstall final state.
set -u

systemctl stop cachyuninstall-helper.service 2>/dev/null
sleep 1

echo "=== build (as tester) ==="
su -s /bin/bash tester -c 'cd /mnt/cachyuninstall && makepkg -f' 2>&1 | grep -E 'Finished making|passed|error' | tail -3

echo "=== install ==="
pacman -U --noconfirm /mnt/cachyuninstall/cachyuninstall-1.0.0-1-any.pkg.tar.zst 2>&1 | grep -E 'upgrading|reinstalling|error' | tail -2
systemctl daemon-reload
systemctl restart dbus
sleep 1
systemctl restart cachyuninstall-helper.service && sleep 2
echo "helper: $(systemctl is-active cachyuninstall-helper.service)"

echo "=== runtime pycache probe ==="
cachyuninstall --list > /dev/null 2>&1 && echo "ran --list ok"
if [ -d /usr/lib/python3.14/site-packages/cachyuninstall/__pycache__ ]; then
  echo "pycache EXISTS: $(ls /usr/lib/python3.14/site-packages/cachyuninstall/__pycache__ | wc -l) files"
else
  echo "pycache: not created"
fi

echo "=== self-uninstall ==="
pacman -Ql cachyuninstall | sed 's|^cachyuninstall ||' > /tmp/pacfiles3.list
echo "tracked entries: $(wc -l < /tmp/pacfiles3.list)"
pacman -R --noconfirm cachyuninstall 2>&1 | grep -E 'removing|error' | tail -4

echo "--- tracked paths that still exist (shared system dirs expected) ---"
while IFS= read -r p; do
  [ -e "$p" ] || continue
  case "$p" in
    /usr/|/usr/bin/|/usr/lib/|/usr/lib/python3.14/|/usr/lib/python3.14/site-packages/|\
    /usr/lib/systemd/|/usr/lib/systemd/system/|/usr/share/|/usr/share/applications/|\
    /usr/share/dbus-1/|/usr/share/dbus-1/system-services/|/usr/share/dbus-1/system.d/|\
    /usr/share/doc/|/usr/share/icons/|/usr/share/icons/hicolor/|\
    /usr/share/icons/hicolor/scalable/|/usr/share/icons/hicolor/scalable/apps/|\
    /usr/share/licenses/|/usr/share/metainfo/|/usr/share/polkit-1/|/usr/share/polkit-1/actions/)
      continue ;;  # shared hierarchy dir, expected to remain
    esac
  echo "STRAY: $p"
done < /tmp/pacfiles3.list

echo "--- package-owned dir? ---"
ls -d /usr/lib/python3.14/site-packages/cachyuninstall* 2>&1 | sed 's/^/  /'
echo "--- daemon / private tmp / system-wide remnants ---"
pgrep -af 'cachyuninstall[-]helper' || echo "  no helper process"
ls -d /var/tmp/systemd-private-*cachyuninstall* 2>/dev/null | sed 's/^/  /' || true
find /usr /etc /var -name '*cachyuninstall*' -o -name '*org.cachyos*' 2>/dev/null | grep -v pacman | sed 's/^/  find: /' | head -8
echo "--- user dirs (documented, allowed) ---"
ls -d /root/.local/share/cachyuninstall 2>&1 | sed 's/^/  /'

echo "=== reinstall final state ==="
pacman -U --noconfirm /mnt/cachyuninstall/cachyuninstall-1.0.0-1-any.pkg.tar.zst 2>&1 | grep -E 'upgrading|reinstalling|error' | tail -1
systemctl daemon-reload
systemctl restart dbus
sleep 1
systemctl restart cachyuninstall-helper.service && sleep 2
echo "final helper: $(systemctl is-active cachyuninstall-helper.service)"
echo "final list rows: $(cachyuninstall --list 2>/dev/null | wc -l)"
busctl call org.cachyos.Uninstall /org/cachyos/Uninstall org.cachyos.Uninstall Call s 'garbage' 2>&1 | head -1
echo "=== pkgcert cycle complete ==="
