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
        title: 'GeoIP refresh requested',
        description: 'Re-tested the assigned proxy.',
        tone: 'success',
      });
    } catch (error) {
      toast({
        title: 'Could not refresh GeoIP',
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
        <IconButton label={`Actions for ${profile.name}`} size="sm">
          <MoreHorizontal className="h-4 w-4" />
        </IconButton>
      }
    >
      <MenuGroup label="Profile">
        <MenuItem
          icon={<Settings2 className="h-4 w-4" />}
          onSelect={() => navigate(`/profiles/${profile.id}/edit`)}
        >
          Edit profile
        </MenuItem>
        <MenuItem
          icon={profile.pinned ? <PinOff className="h-4 w-4" /> : <Pin className="h-4 w-4" />}
          onSelect={() => pin.mutate({ id: profile.id, pinned: !profile.pinned })}
        >
          {profile.pinned ? 'Unpin' : 'Pin'} profile
        </MenuItem>
        <MenuItem
          icon={<FolderInput className="h-4 w-4" />}
          onSelect={() => onDialog('move-folder', profile)}
        >
          {profile.folder_id ? 'Move to another folder' : 'Add to folder'}
        </MenuItem>
        <MenuItem
          icon={<CopyPlus className="h-4 w-4" />}
          onSelect={() => duplicate.mutate(profile.id)}
        >
          Duplicate profile
        </MenuItem>
        <MenuItem
          icon={<Fingerprint className="h-4 w-4" />}
          onSelect={() => onDialog('regenerate', profile)}
        >
          Change fingerprint
        </MenuItem>
      </MenuGroup>

      <MenuSeparator />
      <MenuGroup label="Data">
        <MenuItem
          icon={<Upload className="h-4 w-4" />}
          onSelect={() => onDialog('import-cookies', profile)}
        >
          Import cookies
        </MenuItem>
        <MenuItem
          icon={<Download className="h-4 w-4" />}
          onSelect={() => onDialog('export', profile)}
        >
          Export configuration
        </MenuItem>
        <MenuItem
          icon={<FolderOpen className="h-4 w-4" />}
          onSelect={() => copy(path, 'profile path')}
        >
          Open profile folder
        </MenuItem>
      </MenuGroup>

      <MenuSeparator />
      <MenuGroup label="Proxy &amp; diagnostics">
        <MenuItem
          icon={<Globe2 className="h-4 w-4" />}
          onSelect={() => onDialog('assign-proxy', profile)}
        >
          Assign / edit proxy
        </MenuItem>
        <MenuItem
          icon={<FileJson className="h-4 w-4" />}
          disabled={!profile.proxy?.id}
          onSelect={() => onDialog('proxy-report', profile)}
        >
          View proxy-quality report
        </MenuItem>
        <MenuItem
          icon={<MapPin className="h-4 w-4" />}
          disabled={!profile.proxy?.id}
          onSelect={refreshGeoip}
        >
          Refresh GeoIP alignment
        </MenuItem>
      </MenuGroup>

      <MenuSeparator />
      <MenuGroup label="Runtime">
        {running || busy ? (
          <MenuItem
            icon={<Square className="h-4 w-4" />}
            disabled={busy}
            onSelect={() => stop.mutate(profile.id)}
          >
            Stop profile
          </MenuItem>
        ) : (
          <MenuItem icon={<Play className="h-4 w-4" />} onSelect={() => start.mutate(profile.id)}>
            Start profile
          </MenuItem>
        )}
        <MenuItem
          icon={<Send className="h-4 w-4" />}
          disabled={!running}
          onSelect={() => focus.mutate(profile.id)}
        >
          Bring window to front
        </MenuItem>
        <MenuItem
          icon={<ScrollText className="h-4 w-4" />}
          onSelect={() => onDialog('logs', profile)}
        >
          View runtime logs
        </MenuItem>
      </MenuGroup>

      <MenuSeparator />
      <MenuGroup label="Copy">
        <MenuItem
          icon={<Copy className="h-4 w-4" />}
          onSelect={() => copy(profile.id, 'profile ID')}
        >
          Profile ID
        </MenuItem>
        <MenuItem icon={<Copy className="h-4 w-4" />} onSelect={() => copy(path, 'profile path')}>
          Profile path
        </MenuItem>
        <MenuItem
          icon={<Copy className="h-4 w-4" />}
          disabled={!profile.proxy?.masked_endpoint}
          onSelect={() => copy(profile.proxy?.masked_endpoint ?? '', 'masked proxy endpoint')}
        >
          Masked proxy endpoint
        </MenuItem>
        <MenuItem
          icon={<Copy className="h-4 w-4" />}
          onSelect={() => copy(profile.fingerprint_seed, 'fingerprint seed')}
        >
          Fingerprint seed
        </MenuItem>
        <MenuItem
          icon={<Copy className="h-4 w-4" />}
          onSelect={() => copy(launchExample, 'launch example')}
        >
          Credential-free launch example
        </MenuItem>
      </MenuGroup>

      <MenuSeparator />
      {/* No Share / Transfer actions in v1 (spec §6). */}
      <MenuGroup label="Danger zone">
        <MenuItem
          tone="danger"
          icon={<Trash2 className="h-4 w-4" />}
          onSelect={() => onDialog('trash', profile)}
        >
          Move profile to trash
        </MenuItem>
      </MenuGroup>
    </Menu>
  );
}
