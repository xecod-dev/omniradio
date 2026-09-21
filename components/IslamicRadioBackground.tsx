import React, { useEffect, useRef, useMemo, useState } from 'react';

export type IslamicThemeMode = 'auto' | 'tahajjud' | 'fajr' | 'duha' | 'dhuhr' | 'maghrib' | 'emerald' | 'midnight';

export interface IslamicRadioBackgroundProps {
  /**
   * Toggles the active streaming state.
   * Speeds up subtle ambient breathing glow and slightly elevates illumination depth.
   */
  isPlaying?: boolean;
  /**
   * Background theme mode:
   * - 'auto': Dynamically transitions background colors based on the current hour (Salah cycle).
   * - 'tahajjud' | 'midnight': Deep midnight celestial navy-black (#02050E to #060F1E).
   * - 'fajr': Dawn twilight with rosy gold mist (#050E18 to #122428).
   * - 'duha': Serene morning emerald (#021813 to #052C22).
   * - 'dhuhr' | 'emerald': Majestic mosque dome emerald (#031C15 to #062A20).
   * - 'maghrib': Sunset velvet dusk (#080718 to #120E24).
   * Default: 'auto'
   */
  theme?: IslamicThemeMode;
  /**
   * Optional manual override for Hijri Day (1 - 30).
   * If omitted, automatically determined via `Intl.DateTimeFormat` with Umm al-Qura calendar.
   */
  hijriDay?: number;
  /**
   * Whether to display the Hijri lunar moon.
   * Default: true
   */
  showMoon?: boolean;
  /**
   * Interactive child elements (Radio Player UI, station list, title banner, etc.).
   */
  children?: React.ReactNode;
  /**
   * Optional custom wrapper class name.
   */
  className?: string;
}

interface GlowingStar {
  x: number;
  y: number;
  radius: number;
  alpha: number;
  targetAlpha: number;
  twinkleSpeed: number;
  glow: number;
  golden: boolean;
  vx: number;
  vy: number;
}

function resolveHijriDay(override?: number): { day: number; formattedDate: string } {
  if (typeof override === 'number' && override >= 1 && override <= 30) {
    return { day: override, formattedDate: `اليوم ${override} هـ` };
  }
  let day = 1;
  let formattedDate = '';
  const locales = ['en-u-ca-islamic-umalqura', 'en-u-ca-islamic', 'en-u-ca-islamic-civil'];
  for (const loc of locales) {
    try {
      const parts = new Intl.DateTimeFormat(loc, { day: 'numeric' }).formatToParts(new Date());
      const dayPart = parts.find((p) => p.type === 'day');
      if (dayPart) {
        const val = parseInt(dayPart.value, 10);
        if (!isNaN(val) && val >= 1 && val <= 30) {
          day = val;
          break;
        }
      }
    } catch {
      // locale unsupported, continue
    }
  }
  if (!day || day < 1 || day > 30) {
    const knownNewMoon = new Date('2026-09-11T12:00:00Z').getTime();
    const diffDays = (Date.now() - knownNewMoon) / (1000 * 60 * 60 * 24);
    day = Math.floor(diffDays % 29.53059) + 1;
  }
  try {
    formattedDate = new Intl.DateTimeFormat('ar-u-ca-islamic-umalqura', {
      day: 'numeric',
      month: 'long',
    }).format(new Date());
  } catch {
    formattedDate = `${day} ربيع الآخر`;
  }
  return { day: Math.min(Math.max(day, 1), 30), formattedDate };
}

export const IslamicRadioBackground: React.FC<IslamicRadioBackgroundProps> = ({
  isPlaying = false,
  theme = 'auto',
  hijriDay: userHijriDay,
  showMoon = true,
  children,
  className = '',
}) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const animationFrameRef = useRef<number | null>(null);

  const [hijriInfo, setHijriInfo] = useState<{ day: number; formattedDate: string }>(() =>
    resolveHijriDay(userHijriDay)
  );

  useEffect(() => {
    setHijriInfo(resolveHijriDay(userHijriDay));
  }, [userHijriDay]);

  // Determine active color theme based on hour of day
  const palette = useMemo(() => {
    const now = new Date();
    const currentHour = now.getHours() + now.getMinutes() / 60;

    let selectedMode = theme;
    if (selectedMode === 'auto') {
      if (currentHour >= 0 && currentHour < 4.5) selectedMode = 'tahajjud';
      else if (currentHour >= 4.5 && currentHour < 6.5) selectedMode = 'fajr';
      else if (currentHour >= 6.5 && currentHour < 11.5) selectedMode = 'duha';
      else if (currentHour >= 11.5 && currentHour < 17.5) selectedMode = 'dhuhr';
      else selectedMode = 'maghrib';
    }

    switch (selectedMode) {
      case 'tahajjud':
      case 'midnight':
        return {
          bg1: '#02050E',
          bg2: '#060F1E',
          starIntensity: 0.95,
          glowColor: isPlaying ? 'rgba(30, 58, 138, 0.28)' : 'rgba(30, 58, 138, 0.16)',
          faintStroke: 'rgba(212, 175, 55, 0.12)',
        };
      case 'fajr':
        return {
          bg1: '#050E18',
          bg2: '#122428',
          starIntensity: 0.65,
          glowColor: isPlaying ? 'rgba(212, 175, 55, 0.24)' : 'rgba(212, 175, 55, 0.12)',
          faintStroke: 'rgba(212, 175, 55, 0.14)',
        };
      case 'duha':
        return {
          bg1: '#021813',
          bg2: '#052C22',
          starIntensity: 0.35,
          glowColor: isPlaying ? 'rgba(16, 185, 129, 0.24)' : 'rgba(16, 185, 129, 0.12)',
          faintStroke: 'rgba(212, 175, 55, 0.10)',
        };
      case 'dhuhr':
      case 'emerald':
      default:
        return {
          bg1: '#031C15',
          bg2: '#062A20',
          starIntensity: 0.35,
          glowColor: isPlaying ? 'rgba(212, 175, 55, 0.25)' : 'rgba(212, 175, 55, 0.12)',
          faintStroke: 'rgba(212, 175, 55, 0.12)',
        };
      case 'maghrib':
        return {
          bg1: '#080718',
          bg2: '#120E24',
          starIntensity: 0.85,
          glowColor: isPlaying ? 'rgba(168, 85, 247, 0.25)' : 'rgba(168, 85, 247, 0.14)',
          faintStroke: 'rgba(212, 175, 55, 0.14)',
        };
    }
  }, [theme, isPlaying]);

  // Astronomical Moon Phase & Size calculation
  const moonRenderData = useMemo(() => {
    const day = hijriInfo.day;
    const r = 36;
    // Dynamic sizing based on Hijri day: crescents are smaller ~0.82, full moon grows to ~1.28
    const scale = 0.82 + 0.44 * (1 - Math.abs(day - 14.5) / 14.5);

    let pathD = '';
    let isFull = false;
    let phaseName = '';

    if (day >= 13 && day <= 16) {
      isFull = true;
      phaseName = 'بدر التمام';
    } else {
      const phi = ((day - 1) / 29.5) * 2 * Math.PI;
      const cosPhi = Math.cos(phi);
      const rx = Math.max(Math.abs(r * cosPhi), 0.5);

      if (day < 14) {
        // Waxing
        phaseName = cosPhi > 0 ? (day <= 3 ? 'هلال أول' : 'هلال متزايد') : 'أحدب متزايد';
        const sweepTerm = cosPhi > 0 ? 0 : 1;
        pathD = `M 50,${50 - r} A ${r},${r} 0 0 1 50,${50 + r} A ${rx.toFixed(1)},${r} 0 0 ${sweepTerm} 50,${50 - r} Z`;
      } else {
        // Waning
        phaseName = cosPhi > 0 ? (day >= 27 ? 'هلال أخير' : 'هلال متناقص') : 'أحدب متناقص';
        const sweepTerm = cosPhi > 0 ? 0 : 1;
        pathD = `M 50,${50 - r} A ${r},${r} 0 0 0 50,${50 + r} A ${rx.toFixed(1)},${r} 0 0 ${sweepTerm} 50,${50 - r} Z`;
      }
    }

    return { scale, isFull, pathD, phaseName, r };
  }, [hijriInfo.day]);

  // Small Glowing Star Dots Canvas System
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d', { alpha: true });
    if (!ctx) return;

    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    let width = (canvas.width = window.innerWidth);
    let height = (canvas.height = window.innerHeight);

    const handleResize = () => {
      if (!canvas) return;
      width = canvas.width = window.innerWidth;
      height = canvas.height = window.innerHeight;
    };

    window.addEventListener('resize', handleResize, { passive: true });

    // 70 small glowing star dots
    const starCount = 70;
    const stars: GlowingStar[] = [];

    for (let i = 0; i < starCount; i++) {
      stars.push({
        x: Math.random() * width,
        y: Math.random() * height,
        radius: Math.random() * 1.3 + 0.7, // small delicate glow dot (0.7px to 2.0px)
        alpha: Math.random() * 0.7 + 0.2,
        targetAlpha: Math.random() * 0.7 + 0.2,
        twinkleSpeed: Math.random() * 0.012 + 0.004,
        glow: Math.random() * 5 + 3,
        golden: Math.random() > 0.45,
        vx: (Math.random() - 0.5) * 0.08,
        vy: -Math.random() * 0.12 - 0.02,
      });
    }

    let lastTime = performance.now();

    const render = (time: number) => {
      const dt = Math.min((time - lastTime) / 16.67, 2.0);
      lastTime = time;

      ctx.clearRect(0, 0, width, height);

      const motionSpeedMultiplier = prefersReducedMotion ? 0.1 : isPlaying ? 1.25 : 1.0;

      for (let i = 0; i < starCount; i++) {
        const s = stars[i];

        // Sinusoidal Twinkle
        if (s.alpha < s.targetAlpha) {
          s.alpha += s.twinkleSpeed * dt;
          if (s.alpha >= s.targetAlpha) s.targetAlpha = Math.random() * 0.75 + 0.15;
        } else {
          s.alpha -= s.twinkleSpeed * dt;
          if (s.alpha <= s.targetAlpha) s.targetAlpha = Math.random() * 0.75 + 0.15;
        }

        s.x += s.vx * motionSpeedMultiplier * dt;
        s.y += s.vy * motionSpeedMultiplier * dt;

        if (s.y < -10) {
          s.y = height + 10;
          s.x = Math.random() * width;
        }
        if (s.x < -10) s.x = width + 10;
        if (s.x > width + 10) s.x = -10;

        const effectiveAlpha = Math.min(Math.max(s.alpha * palette.starIntensity, 0.05), 1.0);

        // Draw glowing star dot with shadowBlur
        ctx.save();
        ctx.shadowBlur = s.glow;
        ctx.shadowColor = s.golden
          ? `rgba(255, 235, 170, ${effectiveAlpha.toFixed(3)})`
          : `rgba(225, 240, 255, ${effectiveAlpha.toFixed(3)})`;
        ctx.fillStyle = s.golden
          ? `rgba(255, 245, 205, ${effectiveAlpha.toFixed(3)})`
          : `rgba(255, 255, 255, ${effectiveAlpha.toFixed(3)})`;

        ctx.beginPath();
        ctx.arc(s.x, s.y, s.radius, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      }

      animationFrameRef.current = requestAnimationFrame(render);
    };

    animationFrameRef.current = requestAnimationFrame(render);

    return () => {
      window.removeEventListener('resize', handleResize);
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
      }
    };
  }, [isPlaying, palette.starIntensity]);

  return (
    <div
      className={`relative min-h-screen w-full select-none text-slate-100 transition-colors duration-1000 ${className}`}
      style={{
        background: `linear-gradient(180deg, ${palette.bg1} 0%, ${palette.bg2} 100%)`,
      }}
    >
      <style>{`
        @keyframes subtleRotateSlow {
          0% { transform: rotate(0deg) translateZ(0); }
          100% { transform: rotate(360deg) translateZ(0); }
        }
        @keyframes spiritualBreathe {
          0%, 100% {
            opacity: 0.55;
            transform: scale(0.96) translateZ(0);
          }
          50% {
            opacity: 0.95;
            transform: scale(1.06) translateZ(0);
          }
        }
        @keyframes moonAuraPulse {
          0%, 100% {
            filter: drop-shadow(0 0 8px rgba(255, 235, 170, 0.55)) drop-shadow(0 0 20px rgba(255, 215, 120, 0.25));
            opacity: 0.90;
          }
          50% {
            filter: drop-shadow(0 0 14px rgba(255, 240, 185, 0.85)) drop-shadow(0 0 32px rgba(255, 220, 130, 0.45));
            opacity: 1.0;
          }
        }

        .anim-subtle-spin {
          animation: subtleRotateSlow 180s linear infinite;
          transform-origin: 250px 250px;
          will-change: transform;
        }
        .anim-breathe-glow {
          animation: spiritualBreathe ${isPlaying ? '4.5s' : '8s'} ease-in-out infinite;
          will-change: transform, opacity;
        }
        .anim-moon-pulse {
          animation: moonAuraPulse 6s ease-in-out infinite;
        }

        @media (prefers-reduced-motion: reduce) {
          .anim-subtle-spin,
          .anim-breathe-glow,
          .anim-moon-pulse {
            animation: none !important;
          }
        }
      `}</style>

      {/* BACKGROUND LAYER: fixed, non-interactive, hardware-accelerated */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none -z-10" aria-hidden="true">
        {/* Central Audio-Reactive Ambient Radial Glow */}
        <div
          className="anim-breathe-glow absolute top-[28%] left-1/2 -translate-x-1/2 -translate-y-1/2 w-[550px] h-[550px] md:w-[700px] md:h-[700px] rounded-full pointer-events-none transition-all duration-700"
          style={{
            background: `radial-gradient(circle, ${palette.glowColor} 0%, transparent 70%)`,
            filter: 'blur(75px)',
          }}
        />

        {/* Small Glowing Star Dots Canvas */}
        <canvas ref={canvasRef} className="absolute inset-0 w-full h-full pointer-events-none" />

        {/* Reduced, Whisper-Thin 8-Pointed Star Watermark (Non-Intrusive) */}
        <div className="absolute top-[28%] left-1/2 -translate-x-1/2 -translate-y-1/2 w-[500px] h-[500px] opacity-[0.09] pointer-events-none transition-opacity duration-700">
          <svg viewBox="0 0 500 500" className="w-full h-full" fill="none" xmlns="http://www.w3.org/2000/svg">
            <defs>
              <linearGradient id="reactFaintGold" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stopColor="#DFB76C" stopOpacity="0.8" />
                <stop offset="100%" stopColor="#AA7C11" stopOpacity="0.4" />
              </linearGradient>
            </defs>
            <g className="anim-subtle-spin">
              <circle cx="250" cy="250" r="230" stroke="url(#reactFaintGold)" strokeWidth="0.7" strokeDasharray="3 6" opacity="0.4" />
              <circle cx="250" cy="250" r="215" stroke="url(#reactFaintGold)" strokeWidth="0.8" opacity="0.3" />
              <rect x="160" y="160" width="180" height="180" stroke="url(#reactFaintGold)" strokeWidth="1.2" fill="none" opacity="0.6" />
              <rect x="160" y="160" width="180" height="180" transform="rotate(45 250 250)" stroke="url(#reactFaintGold)" strokeWidth="1.2" fill="none" opacity="0.6" />
              <circle cx="250" cy="250" r="28" stroke="url(#reactFaintGold)" strokeWidth="1" fill="none" opacity="0.5" />
              <circle cx="250" cy="250" r="4" fill="#DFB76C" opacity="0.7" />
            </g>
          </svg>
        </div>

        {/* Dynamic Hijri Moon (Size and phase adapt to Hijri calendar day) */}
        {showMoon && (
          <div className="absolute top-5 right-6 sm:top-8 sm:right-10 flex flex-col items-center pointer-events-auto">
            <div
              className="anim-moon-pulse transition-transform duration-500"
              style={{ transform: `scale(${moonRenderData.scale.toFixed(3)})` }}
            >
              <svg width="58" height="58" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
                <defs>
                  <radialGradient id="reactMoonIvoryGrad" cx="42%" cy="38%" r="60%">
                    <stop offset="0%" stopColor="#FFFFFF" />
                    <stop offset="65%" stopColor="#FFF5D6" />
                    <stop offset="100%" stopColor="#DFB76C" />
                  </radialGradient>
                </defs>
                {/* Earthshine subtle outline */}
                <circle cx="50" cy="50" r={moonRenderData.r} fill="rgba(255, 255, 255, 0.04)" stroke="rgba(255, 255, 255, 0.12)" strokeWidth="0.75" />
                {moonRenderData.isFull ? (
                  <circle cx="50" cy="50" r={moonRenderData.r} fill="url(#reactMoonIvoryGrad)" />
                ) : (
                  <path d={moonRenderData.pathD} fill="url(#reactMoonIvoryGrad)" />
                )}
              </svg>
            </div>
            <div className="text-[10px] text-amber-100/75 bg-black/40 border border-amber-500/20 px-2 py-0.5 rounded-full mt-1 whitespace-nowrap backdrop-blur-md font-medium">
              {hijriInfo.formattedDate} • {moonRenderData.phaseName}
            </div>
          </div>
        )}

        {/* Viewport Vignette */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            background: 'radial-gradient(circle at center, transparent 45%, rgba(0, 0, 0, 0.45) 90%, rgba(0, 0, 0, 0.7) 100%)',
          }}
        />
      </div>

      {/* FOREGROUND CONTENT */}
      <div className="relative z-10 w-full pointer-events-auto">{children}</div>
    </div>
  );
};

export default IslamicRadioBackground;
