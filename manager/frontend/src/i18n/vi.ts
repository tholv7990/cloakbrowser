import type { en } from './en';

export const vi: Record<keyof typeof en, string> = {
  'app.tagline': 'Trình quản lý hồ sơ',

  'nav.profiles': 'Hồ sơ',
  'nav.folders': 'Thư mục',
  'nav.proxies': 'Proxy',
  'nav.diagnostics': 'Chẩn đoán',
  'nav.settings': 'Cài đặt',
  'nav.collapse': 'Thu gọn thanh bên',
  'nav.expand': 'Mở rộng thanh bên',

  'title.profiles': 'Hồ sơ',
  'title.folders': 'Thư mục',
  'title.proxies': 'Proxy',
  'title.diagnostics': 'Chẩn đoán',
  'title.settings': 'Cài đặt',
  'title.newProfile': 'Hồ sơ mới',
  'title.editProfile': 'Sửa hồ sơ',

  'header.running': 'Đang chạy {count}',
  'conn.connected': 'Đã kết nối',
  'conn.connecting': 'Đang kết nối',
  'conn.reconnecting': 'Đang kết nối lại',
  'conn.disconnected': 'Mất kết nối',
  'conn.lost':
    'Mất liên lạc với trình quản lý. Đang kết nối lại và đồng bộ trạng thái — các thao tác tạm dừng cho đến khi kết nối trở lại.',

  'theme.light': 'Giao diện sáng',
  'theme.dark': 'Giao diện tối',
  'theme.system': 'Theo hệ thống',
  'lang.label': 'Ngôn ngữ',

  'common.addProfile': 'Thêm hồ sơ',
  'common.quickCreate': 'Tạo nhanh',
  'common.import': 'Nhập',
  'common.export': 'Xuất',
  'common.save': 'Lưu',
  'common.cancel': 'Hủy',
  'common.searchProfiles': 'Tìm theo tên, ghi chú, thẻ, proxy hoặc ID',

  'profiles.tab.all': 'Tất cả hồ sơ',
  'profiles.tab.pinned': 'Đã ghim',
  'profiles.tab.recent': 'Dùng gần đây',
  'profiles.empty.title': 'Chưa có hồ sơ',
  'profiles.empty.desc':
    'Tạo hồ sơ Windows độc lập đầu tiên để bắt đầu mở các phiên trình duyệt ẩn danh.',
  'profiles.noMatch.title': 'Không có hồ sơ phù hợp',
  'profiles.noMatch.desc':
    'Không có hồ sơ nào khớp với tìm kiếm và bộ lọc hiện tại. Hãy điều chỉnh hoặc đặt lại.',

  'auth.appName': 'CloakBrowser Trình quản lý hồ sơ',
  'auth.setupTitle': 'Tạo tài khoản chủ sở hữu',
  'auth.setupSubtitle':
    'Trình quản lý cục bộ này được bảo vệ bằng một tài khoản chủ sở hữu duy nhất. Dữ liệu chỉ nằm trên máy này và không gửi đi đâu.',
  'auth.loginTitle': 'Đăng nhập',
  'auth.loginSubtitle': 'Nhập email và mật khẩu chủ sở hữu để quản lý hồ sơ.',
  'auth.email': 'Email',
  'auth.password': 'Mật khẩu',
  'auth.confirmPassword': 'Xác nhận mật khẩu',
  'auth.signIn': 'Đăng nhập',
  'auth.createAccount': 'Tạo tài khoản',
  'auth.passwordHint': 'Ít nhất 12 ký tự.',
  'auth.mismatch': 'Mật khẩu không khớp.',
  'auth.checking': 'Đang kiểm tra phiên…',
  'auth.locked': 'Trình quản lý đang bị khóa. Đăng nhập để tiếp tục.',
  'auth.signOut': 'Đăng xuất',
};
