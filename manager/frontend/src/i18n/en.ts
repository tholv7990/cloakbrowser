export const en = {
  'app.tagline': 'Profile Manager',

  'nav.profiles': 'Profiles',
  'nav.folders': 'Folders',
  'nav.proxies': 'Proxies',
  'nav.diagnostics': 'Diagnostics',
  'nav.settings': 'Settings',
  'nav.collapse': 'Collapse sidebar',
  'nav.expand': 'Expand sidebar',

  'title.profiles': 'Profiles',
  'title.folders': 'Folders',
  'title.proxies': 'Proxies',
  'title.diagnostics': 'Diagnostics',
  'title.settings': 'Settings',
  'title.newProfile': 'New profile',
  'title.editProfile': 'Edit profile',

  'header.running': '{count} running',
  'conn.connected': 'Connected',
  'conn.connecting': 'Connecting',
  'conn.reconnecting': 'Reconnecting',
  'conn.disconnected': 'Disconnected',
  'conn.lost':
    'Lost contact with the manager. Reconnecting and reconciling runtime state — actions are paused until the connection returns.',

  'theme.light': 'Light theme',
  'theme.dark': 'Dark theme',
  'theme.system': 'Match system theme',
  'lang.label': 'Language',

  'common.addProfile': 'Add profile',
  'common.quickCreate': 'Quick create',
  'common.import': 'Import',
  'common.export': 'Export',
  'common.save': 'Save',
  'common.cancel': 'Cancel',
  'common.searchProfiles': 'Search name, notes, tags, proxy, or ID',

  'profiles.tab.all': 'All profiles',
  'profiles.tab.pinned': 'Pinned',
  'profiles.tab.recent': 'Recently used',
  'profiles.empty.title': 'No profiles yet',
  'profiles.empty.desc':
    'Create your first isolated Windows profile to start launching stealth browser sessions.',
  'profiles.noMatch.title': 'No profiles match',
  'profiles.noMatch.desc':
    'No profiles fit the current search and filters. Adjust or reset them to see more.',

  'auth.appName': 'CloakBrowser Profile Manager',
  'auth.setupTitle': 'Create your owner account',
  'auth.setupSubtitle':
    'This local manager is protected by a single owner login. It stays on this machine and is never sent anywhere.',
  'auth.loginTitle': 'Sign in',
  'auth.loginSubtitle': 'Enter your owner email and password to manage profiles.',
  'auth.email': 'Email',
  'auth.password': 'Password',
  'auth.confirmPassword': 'Confirm password',
  'auth.signIn': 'Sign in',
  'auth.createAccount': 'Create account',
  'auth.passwordHint': 'At least 12 characters.',
  'auth.mismatch': 'Passwords do not match.',
  'auth.checking': 'Checking session…',
  'auth.locked': 'The manager is locked. Sign in to continue.',
  'auth.signOut': 'Sign out',
} as const;
