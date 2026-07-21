import { useNavigate } from 'react-router-dom';
import {
  Copy,
  CopyPlus,
  Fingerprint,
  FolderInput,
  FolderOpen,
  Globe2,
  MoreHorizontal,
  Pin,
  PinOff,
  Play,
  ScrollText,
  Send,
  Settings2,
  Square,
  Trash2,
  Upload,
  Download,
  FileJson,
  MapPin,
} from 'lucide-react';
import { IconButton } from '@/components/ui/IconButton';
import { Menu, MenuGroup, MenuItem, MenuSeparator } from '@/components/ui/Menu';
import { useClipboard } from '@/hooks/useClipboard';
import { useToast } from '@/components/ui/Toast';
import { api } from '@/api';
import { useT } from '@/i18n';
import type { ProfileView } from '@/types/api';
import {
  useDuplicateProfile,
  useFocusWindow,
  usePinToggle,
  useStartProfile,
  useStopProfile,
} from './api';

export type RowDialog =
  | 'move-folder'
  | 'import-cookies'
  | 'export'
  | 'logs'
  | 'assign-proxy'
  | 'proxy-report'
  | 'regenerate'
  | 'trash';

export function ProfileRowActions({
  profile,
  profileRoot,
  onDialog,
}: {
  profile: ProfileView;
  profileRoot: string;
  onDialog: (dialog: RowDialog, profile: ProfileView) => void;
}) {
  const navigate = useNavigate();
  const t = useT();
  const copy = useClipboard();
  const { toast } = useToast();
  const start = useStartProfile();
  const stop = useStopProfile();
  const pin = usePinToggle();
  const duplicate = useDuplicateProfile();
  const focus = useFocusWindow();

  const running = profile.runtime_state === 'running';
  const busy = profile.runtime_state === 'starting' || profile.runtime_state === 'stopping';
  const path = `${profileRoot}\\${profile.id}`;
  const launchExample = `python -m cloakbrowser.manager start --profile ${profile.id}`;

  const refreshGeoip = async () => {
    if (!profile.proxy?.id) return;
    try {
      await api.quickTestProxy(profile.proxy.id);
      toast({
        title: t('row.geoipRequested'),
        description: t('row.geoipRetested'),
        tone: 'success',
      });
    } catch (error) {
      toast({
        title: t('row.geoipFailed'),
        description: (error as Error).message,
        tone: 'danger',
      });
    }
  };

  return (
    <Menu
      align="end"
      width={248}
      trigger={
        <IconButton label={t('row.actionsFor', { name: profile.name })} size="sm">
          <MoreHorizontal className="h-4 w-4" />
        </IconButton>
      }
    >
      <MenuGroup label={t('row.group.profile')}>
        <MenuItem
          icon={<Settings2 className="h-4 w-4" />}
          onSelect={() => navigate(`/profiles/${profile.id}/edit`)}
        >
          {t('row.edit')}
        </MenuItem>
        <MenuItem
          icon={profile.pinned ? <PinOff className="h-4 w-4" /> : <Pin className="h-4 w-4" />}
          onSelect={() => pin.mutate({ id: profile.id, pinned: !profile.pinned })}
        >
          {t(profile.pinned ? 'row.unpin' : 'row.pin')}
        </MenuItem>
        <MenuItem
          icon={<FolderInput className="h-4 w-4" />}
          onSelect={() => onDialog('move-folder', profile)}
        >
          {t(profile.folder_id ? 'row.moveFolder' : 'row.addFolder')}
        </MenuItem>
        <MenuItem
          icon={<CopyPlus className="h-4 w-4" />}
          onSelect={() => duplicate.mutate(profile.id)}
        >
          {t('row.duplicate')}
        </MenuItem>
        <MenuItem
          icon={<Fingerprint className="h-4 w-4" />}
          onSelect={() => onDialog('regenerate', profile)}
        >
          {t('row.changeFingerprint')}
        </MenuItem>
      </MenuGroup>

      <MenuSeparator />
      <MenuGroup label={t('row.group.data')}>
        <MenuItem
          icon={<Upload className="h-4 w-4" />}
          onSelect={() => onDialog('import-cookies', profile)}
        >
          {t('row.importCookies')}
        </MenuItem>
        <MenuItem
          icon={<Download className="h-4 w-4" />}
          onSelect={() => onDialog('export', profile)}
        >
          {t('row.exportConfig')}
        </MenuItem>
        <MenuItem
          icon={<FolderOpen className="h-4 w-4" />}
          onSelect={() => copy(path, 'profile path')}
        >
          {t('row.openFolder')}
        </MenuItem>
      </MenuGroup>

      <MenuSeparator />
      <MenuGroup label={t('row.group.proxyDiag')}>
        <MenuItem
          icon={<Globe2 className="h-4 w-4" />}
          onSelect={() => onDialog('assign-proxy', profile)}
        >
          {t('row.assignProxy')}
        </MenuItem>
        <MenuItem
          icon={<FileJson className="h-4 w-4" />}
          disabled={!profile.proxy?.id}
          onSelect={() => onDialog('proxy-report', profile)}
        >
          {t('row.viewProxyReport')}
        </MenuItem>
        <MenuItem
          icon={<MapPin className="h-4 w-4" />}
          disabled={!profile.proxy?.id}
          onSelect={refreshGeoip}
        >
          {t('row.refreshGeoip')}
        </MenuItem>
      </MenuGroup>

      <MenuSeparator />
      <MenuGroup label={t('row.group.runtime')}>
        {running || busy ? (
          <MenuItem
            icon={<Square className="h-4 w-4" />}
            disabled={busy}
            onSelect={() => stop.mutate(profile.id)}
          >
            {t('row.stop')}
          </MenuItem>
        ) : (
          <MenuItem icon={<Play className="h-4 w-4" />} onSelect={() => start.mutate(profile.id)}>
            {t('row.start')}
          </MenuItem>
        )}
        <MenuItem
          icon={<Send className="h-4 w-4" />}
          disabled={!running}
          onSelect={() => focus.mutate(profile.id)}
        >
          {t('row.bringFront')}
        </MenuItem>
        <MenuItem
          icon={<ScrollText className="h-4 w-4" />}
          onSelect={() => onDialog('logs', profile)}
        >
          {t('row.viewLogs')}
        </MenuItem>
      </MenuGroup>

      <MenuSeparator />
      <MenuGroup label={t('row.group.copy')}>
        <MenuItem
          icon={<Copy className="h-4 w-4" />}
          onSelect={() => copy(profile.id, 'profile ID')}
        >
          {t('row.copyId')}
        </MenuItem>
        <MenuItem icon={<Copy className="h-4 w-4" />} onSelect={() => copy(path, 'profile path')}>
          {t('row.copyPath')}
        </MenuItem>
        <MenuItem
          icon={<Copy className="h-4 w-4" />}
          disabled={!profile.proxy?.masked_endpoint}
          onSelect={() => copy(profile.proxy?.masked_endpoint ?? '', 'masked proxy endpoint')}
        >
          {t('row.copyEndpoint')}
        </MenuItem>
        <MenuItem
          icon={<Copy className="h-4 w-4" />}
          onSelect={() => copy(profile.fingerprint_seed, 'fingerprint seed')}
        >
          {t('row.copySeed')}
        </MenuItem>
        <MenuItem
          icon={<Copy className="h-4 w-4" />}
          onSelect={() => copy(launchExample, 'launch example')}
        >
          {t('row.copyLaunch')}
        </MenuItem>
      </MenuGroup>

      <MenuSeparator />
      {/* No Share / Transfer actions in v1 (spec §6). */}
      <MenuGroup label={t('row.group.danger')}>
        <MenuItem
          tone="danger"
          icon={<Trash2 className="h-4 w-4" />}
          onSelect={() => onDialog('trash', profile)}
        >
          {t('row.trash')}
        </MenuItem>
      </MenuGroup>
    </Menu>
  );
}
