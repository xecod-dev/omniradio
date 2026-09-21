import React, { useEffect, useRef, useMemo } from 'react';

export interface IslamicRadioBackgroundProps {
  /**
   * Toggles the active streaming state.
   * When true, speeds up ambient breathing glow and increases illumination depth.
   */
  isPlaying?: boolean;
  /**
   * Color palette mood:
   * - 'emerald': Deep sacred mosque green (#031B15, #06281E) with warm antique gold.
   * - 'midnight': Nocturnal celestial navy (#070B19, #0B132B) with radiant gold.
   */
  theme?: 'emerald' | 'midnight';
  /**
   * Interactive child elements (Radio Player UI, station list, title banner, etc.).
   */
  children?: React.ReactNode;
  /**
   * Optional custom wrapper class name.
   */
  className?: string;
  /**
   * Whether to display the upper periphery glowing Crescent (Hilal) & Star.
   * Default: true
   */
  showCrescent?: boolean;
}

interface Particle {
  x: number;
  y: number;
  radius: number;
  alpha: number;
  targetAlpha: number;
  vx: number;
  vy: number;
  twinkleSpeed: number;
  golden: boolean;
}

export const IslamicRadioBackground: React.FC<IslamicRadioBackgroundProps> = ({
  isPlaying = false,
  theme = 'emerald',
  children,
  className = '',
  showCrescent = true,
}) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const animationFrameRef = useRef<number | null>(null);

  // Theme-specific color definitions
  const palette = useMemo(() => {
    if (theme === 'midnight') {
      return {
        bgBase: '#070B19',
        bgGradient: 'radial-gradient(ellipse at 50% 30%, #0F172A 0%, #070B19 75%, #04060E 100%)',
        glowColor: isPlaying ? 'rgba(212, 175, 55, 0.22)' : 'rgba(212, 175, 55, 0.10)',
        glowSecondary: isPlaying ? 'rgba(30, 58, 138, 0.35)' : 'rgba(30, 58, 138, 0.18)',
        goldStroke: 'rgba(212, 175, 55, 0.18)',
        goldAccent: '#D4AF37',
        goldGlow: 'rgba(212, 175, 55, 0.35)',
      };
    }
    // Emerald default
    return {
      bgBase: '#031713',
      bgGradient: 'radial-gradient(ellipse at 50% 30%, #06281E 0%, #031713 70%, #010B09 100%)',
      glowColor: isPlaying ? 'rgba(212, 175, 55, 0.24)' : 'rgba(212, 175, 55, 0.12)',
      glowSecondary: isPlaying ? 'rgba(5, 150, 105, 0.28)' : 'rgba(4, 120, 87, 0.14)',
      goldStroke: 'rgba(212, 175, 55, 0.20)',
      goldAccent: '#DFB76C',
      goldGlow: 'rgba(223, 183, 108, 0.35)',
    };
  }, [theme, isPlaying]);

  // Lightweight HTML5 Canvas particle system for stars & spiritual ambient dust
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d', { alpha: true });
    if (!ctx) return;

    // Honor reduced-motion preferences
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    let width = (canvas.width = window.innerWidth);
    let height = (canvas.height = window.innerHeight);

    const handleResize = () => {
      if (!canvas) return;
      width = canvas.width = window.innerWidth;
      height = canvas.height = window.innerHeight;
    };

    window.addEventListener('resize', handleResize, { passive: true });

    // Subtle particle count (40 particles) to guarantee low CPU/GPU usage during live audio playback
    const particleCount = 40;
    const particles: Particle[] = [];

    for (let i = 0; i < particleCount; i++) {
      particles.push({
        x: Math.random() * width,
        y: Math.random() * height,
        radius: Math.random() * 1.5 + 0.5,
        alpha: Math.random() * 0.7 + 0.1,
        targetAlpha: Math.random() * 0.7 + 0.1,
        vx: (Math.random() - 0.5) * 0.15,
        vy: -Math.random() * 0.25 - 0.05, // Gentle upward celestial drift
        twinkleSpeed: Math.random() * 0.015 + 0.005,
        golden: Math.random() > 0.45,
      });
    }

    let lastTime = performance.now();

    const render = (time: number) => {
      const dt = Math.min((time - lastTime) / 16.67, 2.0); // normalize ~60fps
      lastTime = time;

      ctx.clearRect(0, 0, width, height);

      const motionSpeedMultiplier = prefersReducedMotion ? 0.2 : isPlaying ? 1.35 : 1.0;

      for (let i = 0; i < particleCount; i++) {
        const p = particles[i];

        // Smooth sinusoidal twinkle
        if (p.alpha < p.targetAlpha) {
          p.alpha += p.twinkleSpeed * dt;
          if (p.alpha >= p.targetAlpha) {
            p.targetAlpha = Math.random() * 0.75 + 0.1;
          }
        } else {
          p.alpha -= p.twinkleSpeed * dt;
          if (p.alpha <= p.targetAlpha) {
            p.targetAlpha = Math.random() * 0.75 + 0.1;
          }
        }

        // Float motes
        p.x += p.vx * motionSpeedMultiplier * dt;
        p.y += p.vy * motionSpeedMultiplier * dt;

        // Wrap around boundaries smoothly
        if (p.y < -10) {
          p.y = height + 10;
          p.x = Math.random() * width;
        }
        if (p.x < -10) p.x = width + 10;
        if (p.x > width + 10) p.x = -10;

        // Draw particle
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
        if (p.golden) {
          ctx.fillStyle = `rgba(223, 183, 108, ${p.alpha.toFixed(3)})`;
        } else {
          ctx.fillStyle = `rgba(240, 246, 252, ${(p.alpha * 0.8).toFixed(3)})`;
        }
        ctx.fill();
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
  }, [isPlaying]);

  return (
    <div
      className={`relative min-h-screen w-full select-none text-slate-100 ${className}`}
      style={{
        backgroundColor: palette.bgBase,
        backgroundImage: palette.bgGradient,
      }}
    >
      {/* Embedded High-Performance Animations Style Block */}
      <style>{`
        @keyframes girihRotateClockwise {
          0% { transform: rotate(0deg) translateZ(0); }
          100% { transform: rotate(360deg) translateZ(0); }
        }
        @keyframes girihRotateCounter {
          0% { transform: rotate(0deg) translateZ(0); }
          100% { transform: rotate(-360deg) translateZ(0); }
        }
        @keyframes spiritualBreathe {
          0%, 100% {
            opacity: 0.65;
            transform: scale(0.96) translateZ(0);
          }
          50% {
            opacity: 1.0;
            transform: scale(1.06) translateZ(0);
          }
        }
        @keyframes hilalGlowPulse {
          0%, 100% { filter: drop-shadow(0 0 10px rgba(212, 175, 55, 0.45)); opacity: 0.85; }
          50% { filter: drop-shadow(0 0 18px rgba(212, 175, 55, 0.80)); opacity: 1.0; }
        }

        .anim-girih-clockwise {
          animation: girihRotateClockwise ${isPlaying ? '95s' : '140s'} linear infinite;
          transform-origin: 500px 500px;
          will-change: transform;
        }
        .anim-girih-counter {
          animation: girihRotateCounter ${isPlaying ? '65s' : '90s'} linear infinite;
          transform-origin: 500px 500px;
          will-change: transform;
        }
        .anim-breathe-glow {
          animation: spiritualBreathe ${isPlaying ? '4.2s' : '7.5s'} ease-in-out infinite;
          will-change: transform, opacity;
        }
        .anim-hilal-pulse {
          animation: hilalGlowPulse ${isPlaying ? '5s' : '8s'} ease-in-out infinite;
        }

        @media (prefers-reduced-motion: reduce) {
          .anim-girih-clockwise,
          .anim-girih-counter,
          .anim-breathe-glow,
          .anim-hilal-pulse {
            animation: none !important;
          }
        }
      `}</style>

      {/* =========================================================================
          BACKGROUND LAYER: fixed, non-interactive, hardware-accelerated
          ========================================================================= */}
      <div
        className="fixed inset-0 overflow-hidden pointer-events-none -z-10"
        aria-hidden="true"
      >
        {/* Central Audio-Reactive Spiritual Radial Glow */}
        <div
          className="anim-breathe-glow absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[700px] h-[700px] md:w-[950px] md:h-[950px] rounded-full pointer-events-none"
          style={{
            background: `radial-gradient(circle, ${palette.glowColor} 0%, ${palette.glowSecondary} 45%, transparent 70%)`,
            filter: 'blur(50px)',
          }}
        />

        {/* Ambient Floating Dust & Stars Canvas */}
        <canvas
          ref={canvasRef}
          className="absolute inset-0 w-full h-full pointer-events-none opacity-80"
        />

        {/* Authentic Islamic Geometric Girih Mandala (SVG) */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[650px] h-[650px] sm:w-[850px] sm:h-[850px] lg:w-[1100px] lg:h-[1100px] opacity-75">
          <svg
            viewBox="0 0 1000 1000"
            className="w-full h-full"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
          >
            <defs>
              {/* Metallic Gold Gradient */}
              <linearGradient id="goldGradient" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stopColor="#DFB76C" stopOpacity="0.85" />
                <stop offset="50%" stopColor="#D4AF37" stopOpacity="0.5" />
                <stop offset="100%" stopColor="#997526" stopOpacity="0.85" />
              </linearGradient>

              {/* Central Soft Glow Filter */}
              <filter id="softGlow" x="-20%" y="-20%" width="140%" height="140%">
                <feGaussianBlur stdDeviation="3" result="blur" />
                <feComposite in="SourceGraphic" in2="blur" operator="over" />
              </filter>
            </defs>

            {/* LAYER 1: Slow Clockwise Outer 16-Fold Girih Strapwork & Rosette */}
            <g className="anim-girih-clockwise">
              {/* Concentric Calibration Circles */}
              <circle
                cx="500"
                cy="500"
                r="470"
                stroke="url(#goldGradient)"
                strokeWidth="1"
                strokeDasharray="4 8"
                opacity="0.3"
              />
              <circle
                cx="500"
                cy="500"
                r="440"
                stroke="url(#goldGradient)"
                strokeWidth="1.5"
                opacity="0.45"
              />
              <circle
                cx="500"
                cy="500"
                r="380"
                stroke="url(#goldGradient)"
                strokeWidth="0.75"
                opacity="0.25"
              />

              {/* 16 Radial Rays with Arabesque Diamond Terminals */}
              {Array.from({ length: 16 }).map((_, i) => {
                const angle = (i * 360) / 16;
                return (
                  <g key={`ray-${i}`} transform={`rotate(${angle} 500 500)`}>
                    <line
                      x1="500"
                      y1="60"
                      x2="500"
                      y2="120"
                      stroke="url(#goldGradient)"
                      strokeWidth="1.2"
                      opacity="0.4"
                    />
                    {/* Diamond tip */}
                    <polygon
                      points="500,50 505,60 500,70 495,60"
                      fill="url(#goldGradient)"
                      opacity="0.5"
                    />
                    {/* Small star bead at boundary */}
                    <circle cx="500" cy="120" r="2.5" fill="#DFB76C" opacity="0.6" />
                  </g>
                );
              })}

              {/* Interlocking Hexadecagon / 16-Point Girih Star Polygon Lattice */}
              <g stroke="url(#goldGradient)" strokeWidth="1.2" opacity="0.4">
                <polygon points="500,60 626,112 730,195 801,304 832,431 821,561 768,679 676,771 556,827 426,835 303,797 201,718 135,608 113,478 139,349 212,238" />
                <polygon points="500,940 374,888 270,805 199,696 168,569 179,439 232,321 324,229 444,173 574,165 697,203 799,282 865,392 887,522 861,651 788,762" />
              </g>

              {/* Girih Petal Arcs */}
              {Array.from({ length: 8 }).map((_, i) => (
                <path
                  key={`arc-${i}`}
                  d="M 500 120 Q 560 250 500 380 Q 440 250 500 120 Z"
                  transform={`rotate(${i * 45} 500 500)`}
                  stroke="url(#goldGradient)"
                  strokeWidth="0.9"
                  fill="rgba(212, 175, 55, 0.02)"
                  opacity="0.35"
                />
              ))}
            </g>

            {/* LAYER 2: Slow Counter-Clockwise Inner Rub el Hizb (8-Pointed Star Medallion) */}
            <g className="anim-girih-counter" filter="url(#softGlow)">
              {/* Outer 8-pointed star formed by dual interlaced squares */}
              <rect
                x="320"
                y="320"
                width="360"
                height="360"
                stroke="url(#goldGradient)"
                strokeWidth="1.6"
                fill="none"
                opacity="0.55"
              />
              <rect
                x="320"
                y="320"
                width="360"
                height="360"
                transform="rotate(45 500 500)"
                stroke="url(#goldGradient)"
                strokeWidth="1.6"
                fill="none"
                opacity="0.55"
              />

              {/* Middle Interlocking 8-Pointed Star (Rotated 22.5 deg) */}
              <g transform="rotate(22.5 500 500)" stroke="url(#goldGradient)" strokeWidth="1" opacity="0.45">
                <rect x="360" y="360" width="280" height="280" />
                <rect x="360" y="360" width="280" height="280" transform="rotate(45 500 500)" />
              </g>

              {/* Inner Sacred Rosette Pattern */}
              {Array.from({ length: 8 }).map((_, i) => {
                const angle = i * 45;
                return (
                  <g key={`inner-leaf-${i}`} transform={`rotate(${angle} 500 500)`}>
                    <path
                      d="M 500 340 C 515 390 535 410 500 460 C 465 410 485 390 500 340 Z"
                      fill="url(#goldGradient)"
                      fillOpacity="0.07"
                      stroke="url(#goldGradient)"
                      strokeWidth="1.1"
                      opacity="0.75"
                    />
                    <circle cx="500" cy="340" r="3" fill="#F3E5AB" opacity="0.7" />
                  </g>
                );
              })}

              {/* Center Medallion Rings */}
              <circle
                cx="500"
                cy="500"
                r="65"
                stroke="url(#goldGradient)"
                strokeWidth="1.8"
                fill="rgba(3, 23, 19, 0.4)"
                opacity="0.75"
              />
              <circle
                cx="500"
                cy="500"
                r="50"
                stroke="url(#goldGradient)"
                strokeWidth="0.8"
                strokeDasharray="2 4"
                opacity="0.6"
              />
              <circle cx="500" cy="500" r="10" fill="#DFB76C" opacity="0.85" />
            </g>
          </svg>
        </div>

        {/* Elegant Crescent Moon (Hilal) & Venus Star in Upper Right Periphery */}
        {showCrescent && (
          <div className="anim-hilal-pulse absolute top-6 right-6 sm:top-10 sm:right-12 md:top-14 md:right-20 pointer-events-none opacity-90">
            <svg
              width="68"
              height="68"
              viewBox="0 0 100 100"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
            >
              {/* Crescent Path */}
              <path
                d="M 68 18 C 45 22 28 42 28 66 C 28 88 44 106 65 110 C 40 104 22 83 22 58 C 22 34 38 15 62 10 C 64 9.5 66.5 9.2 68 9 C 67.5 12 67.5 15 68 18 Z"
                fill="url(#hilalGoldGradient)"
              />
              {/* Companion Morning Star (Rub el Hizb miniature) */}
              <g transform="translate(68, 28) scale(0.65)">
                <polygon
                  points="10,0 12.5,7.5 20,10 12.5,12.5 10,20 7.5,12.5 0,10 7.5,7.5"
                  fill="#F9E79F"
                />
                <circle cx="10" cy="10" r="2" fill="#FFFFFF" />
              </g>
              <defs>
                <linearGradient
                  id="hilalGoldGradient"
                  x1="20%"
                  y1="10%"
                  x2="90%"
                  y2="90%"
                >
                  <stop offset="0%" stopColor="#FFF2B2" />
                  <stop offset="60%" stopColor="#DFB76C" />
                  <stop offset="100%" stopColor="#AA7C11" />
                </linearGradient>
              </defs>
            </svg>
          </div>
        )}

        {/* Subtle Vignette Shading on Viewport Edges */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            background:
              'radial-gradient(circle at center, transparent 40%, rgba(0, 0, 0, 0.45) 90%, rgba(0, 0, 0, 0.75) 100%)',
          }}
        />
      </div>

      {/* =========================================================================
          FOREGROUND CONTENT CONTAINER: clickable, unobstructed, elevated z-index
          ========================================================================= */}
      <div className="relative z-10 w-full pointer-events-auto">
        {children}
      </div>
    </div>
  );
};

export default IslamicRadioBackground;
