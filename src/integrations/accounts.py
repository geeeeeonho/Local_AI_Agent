"""LocalAI account administration on this PC: see everyone, read no one.

A LocalAI administrator can list the PC's Windows accounts, allow or remove
them, make them administrators, limit LocalAI to allowed accounts, and delete
an account's LocalAI records. Nothing here opens another account's records:
they are encrypted with that account's own key, and deleting them does not
need to read them.

Group membership changes and deletion need a Windows administrator (one UAC
prompt each). Permission changes on the shared folders do not: a LocalAI
administrator holds full control of them.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from core import accounts, machine
from integrations.windows import acl
from integrations.windows import machine as windows


class AccountAdmin:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.policy_path = self.root / machine.POLICY_FILENAME
        self.users_root = self.root / 'users'

    # ── reading ──────────────────────────────────────────────────────────
    def _policy(self) -> Optional[machine.Policy]:
        return machine.load(self.policy_path)

    def _identity(self):
        return acl.current_user_sid(), windows.token_group_sids()

    def is_admin(self) -> bool:
        policy = self._policy()
        if policy is None:
            return False
        sid, groups = self._identity()
        return policy.is_admin(sid, groups)

    def overview(self) -> dict:
        if not acl.on_windows():
            return {'available': False, 'reason': '계정 관리는 Windows에서만 사용할 수 있습니다.'}
        policy = self._policy()
        sid, groups = self._identity()
        if policy is None:
            return {'available': False,
                    'reason': '아직 LocalAI 관리자가 정해지지 않았습니다. 처음 설치한 계정에서 '
                              '[설치 / 복구]를 실행하세요.'}
        listing = windows.list_accounts()
        if listing is None:
            return {'available': False, 'reason': 'Windows 계정 목록을 읽지 못했습니다.'}
        admins = {item.upper() for item in policy.admins} | listing['admins']
        rows = []
        for user in listing['users']:
            key = user['sid'].upper()
            admin = key in admins
            member = key in listing['members']
            allowed = admin or (policy.access == machine.ACCESS_EVERYONE) or member
            rows.append({
                'name': user['name'], 'sid': user['sid'], 'disabled': user['disabled'],
                'admin': admin, 'member': member,
                'allowed': allowed and not user['disabled'],
                'records': windows.records_folder(self.users_root, user['name']).exists(),
                'me': bool(sid and key == sid.upper()),
            })
        rows.sort(key=lambda row: (not row['me'], not row['admin'], row['name'].lower()))
        return {'available': True, 'is_admin': policy.is_admin(sid, groups),
                'access': policy.access, 'rows': rows,
                'groups_ready': bool(policy.admins_group_sid and policy.users_group_sid)}

    # ── changing ─────────────────────────────────────────────────────────
    def _require_admin(self) -> machine.Policy:
        policy = self._policy()
        sid, groups = self._identity()
        if policy is None or not policy.is_admin(sid, groups):
            raise RuntimeError('LocalAI 관리자만 할 수 있습니다.')
        return policy

    def _write(self, policy: machine.Policy) -> None:
        tmp = self.policy_path.with_name(self.policy_path.name + '.tmp')
        tmp.write_text(policy.to_json(), encoding='utf-8')
        tmp.replace(self.policy_path)

    def _account(self, sid: str) -> dict:
        listing = windows.list_accounts() or {'users': []}
        for user in listing['users']:
            if user['sid'].upper() == str(sid).upper():
                return user
        raise RuntimeError('이 PC에서 그 계정을 찾지 못했습니다: %s' % sid)

    def set_allowed(self, sid: str, allowed: bool, *, log=None) -> str:
        self._require_admin()
        user = self._account(sid)
        script = windows.membership_script(machine.USERS_GROUP, user['sid'], allowed)
        if not script or not windows.run_as_admin(script, log=log):
            raise RuntimeError('LocalAI-Users 그룹을 바꾸지 못했습니다.')
        return ('%s 계정의 LocalAI 사용을 %s했습니다. 그 계정이 다시 로그인하면 적용됩니다.'
                % (user['name'], '허용' if allowed else '해제'))

    def set_admin(self, sid: str, admin: bool, *, log=None) -> str:
        policy = self._require_admin()
        user = self._account(sid)
        if not admin:
            remaining = [item for item in policy.admins if item.upper() != user['sid'].upper()]
            listing = windows.list_accounts() or {'admins': set()}
            others = {item for item in listing['admins'] if item != user['sid'].upper()}
            if not remaining and not others:
                raise RuntimeError('마지막 LocalAI 관리자는 해제할 수 없습니다. 먼저 다른 관리자를 지정하세요.')
        script = windows.membership_script(machine.ADMINS_GROUP, user['sid'], admin)
        if not script or not windows.run_as_admin(script, log=log):
            raise RuntimeError('LocalAI-Admins 그룹을 바꾸지 못했습니다.')
        policy = policy.with_admin(user['sid'], admin)
        self._write(policy)
        if not admin:
            acl.run(windows.remove_grants_command(self.root, user['sid']), timeout=600)
        if not acl.succeeded(acl.run(windows.lock_root_command(self.root, policy), timeout=600)):
            raise RuntimeError('공용 폴더 권한을 갱신하지 못했습니다: %s' % self.root)
        return ('%s 계정을 LocalAI 관리자%s. 그룹 변경은 그 계정이 다시 로그인하면 적용됩니다.'
                % (user['name'], '로 지정했습니다' if admin else '에서 해제했습니다'))

    def delete_records(self, sid: str, *, log=None) -> str:
        self._require_admin()
        me, _groups = self._identity()
        user = self._account(sid)
        if me and user['sid'].upper() == me.upper():
            raise RuntimeError('지금 로그인한 계정의 기록은 여기서 지울 수 없습니다.')
        folder = windows.records_folder(self.users_root, user['name'])
        if not folder.exists():
            return '%s 계정의 LocalAI 기록이 없습니다.' % user['name']
        script = windows.delete_records_script(folder, self.users_root)
        if not script or not windows.run_as_admin(script, log=log):
            raise RuntimeError('기록을 삭제하지 못했습니다: %s' % folder)
        return '%s 계정의 LocalAI 기록을 삭제했습니다 (내용은 열어 보지 않았습니다).' % user['name']

    def set_access(self, mode: str, *, log=None) -> str:
        if mode not in (machine.ACCESS_EVERYONE, machine.ACCESS_MEMBERS):
            raise ValueError('unknown access mode')
        policy = self._require_admin()
        if mode == machine.ACCESS_MEMBERS and not policy.users_group_sid:
            raise RuntimeError('LocalAI-Users 그룹이 아직 없습니다. [설치 / 복구]를 한 번 실행하세요.')
        previous = policy.principal()
        policy.access = mode
        self._write(policy)
        failed = [command for command in windows.access_commands(self.root, policy, previous)
                  if not acl.succeeded(acl.run(command, timeout=900))]
        if failed:
            raise RuntimeError('일부 공용 폴더 권한을 바꾸지 못했습니다: %s'
                               % ', '.join(command[1] for command in failed[:3]))
        if mode == machine.ACCESS_MEMBERS:
            return ('이제 LocalAI 관리자와 허용된 계정만 사용할 수 있습니다. '
                    '허용한 계정은 다시 로그인해야 적용됩니다.')
        return '이제 이 PC의 모든 Windows 계정이 LocalAI를 사용할 수 있습니다.'


def folder_for(root: Path, name: str) -> Path:
    return Path(root) / 'users' / accounts.slug(name)


__all__ = ['AccountAdmin', 'folder_for']
