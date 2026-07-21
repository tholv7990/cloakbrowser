import { LogoMark } from '@/components/Logo';

/**
 * Login hero background. Original CloakBrowser composition (no third-party
 * assets): a deep gradient, soft accent glows, a fine grid, and a large faint
 * mark — evoking a stealth/security surface. Pass `imageUrl` (or set
 * VITE_AUTH_BG_URL) to swap in your own photo; a dark scrim keeps text legible.
 */
export function AuthBackground({ imageUrl }: { imageUrl?: string }) {
  if (imageUrl) {
    return (
      <div className="absolute inset-0">
        <div
          className="absolute inset-0 bg-cover bg-center"
          style={{ backgroundImage: `url(${imageUrl})` }}
        />
        <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-black/40 to-black/30" />
      </div>
    );
  }

  return (
    <div
      className="absolute inset-0"
      style={{
        background:
          'radial-gradient(90% 80% at 15% 10%, rgba(47,111,235,0.38), transparent 60%),' +
          'radial-gradient(80% 70% at 90% 90%, rgba(45,212,191,0.22), transparent 55%),' +
          'linear-gradient(150deg, #0b1220 0%, #0d1730 55%, #0a0f1c 100%)',
      }}
    >
      {/* Fine grid */}
      <div
        className="absolute inset-0 opacity-[0.06]"
        style={{
          backgroundImage:
            'linear-gradient(rgba(255,255,255,0.9) 1px, transparent 1px),' +
            'linear-gradient(90deg, rgba(255,255,255,0.9) 1px, transparent 1px)',
          backgroundSize: '44px 44px',
        }}
      />
      {/* Soft blurred blobs for depth */}
      <div className="absolute -left-24 top-10 h-72 w-72 rounded-full bg-[#2F6FEB] opacity-30 blur-3xl" />
      <div className="absolute -right-16 bottom-4 h-80 w-80 rounded-full bg-[#22d3ee] opacity-20 blur-3xl" />
      {/* Large faint brand mark */}
      <LogoMark size={520} className="absolute -bottom-40 -right-32 opacity-[0.05]" />
      {/* Vignette */}
      <div className="absolute inset-0 bg-gradient-to-t from-black/40 to-transparent" />
    </div>
  );
}
