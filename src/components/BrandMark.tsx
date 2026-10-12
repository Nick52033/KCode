import { useId } from "react";

interface BrandMarkProps {
  size?: number;
  className?: string;
}

/**
 * KCode 品牌标识：黑色圆角方块 + 银白渐变 K。
 *
 * 渐变 id 必须按实例唯一：同一页面会同时渲染多个 BrandMark（标题栏、对话框、
 * 子智能体面板），复用一个固定 id 时浏览器只会解析 DOM 中第一个定义，
 * 实例被卸载后其余实例会掉回无渐变状态。
 */
export function BrandMark({ size = 20, className }: BrandMarkProps) {
  const gradientId = useId();
  const backgroundId = `kcode-bg-${gradientId}`;
  const glyphId = `kcode-glyph-${gradientId}`;
  const trailId = `kcode-trail-${gradientId}`;
  return (
    <svg
      className={className}
      data-brand-mark="k-letter"
      viewBox="0 0 512 512"
      width={size}
      height={size}
      fill="none"
      aria-hidden="true"
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <linearGradient id={backgroundId} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#1A1A1E" />
          <stop offset="0.55" stopColor="#0C0C0E" />
          <stop offset="1" stopColor="#000000" />
        </linearGradient>
        <linearGradient id={glyphId} x1="0.18" y1="0" x2="0.85" y2="1">
          <stop offset="0" stopColor="#FFFFFF" />
          <stop offset="0.5" stopColor="#E8E8EF" />
          <stop offset="1" stopColor="#A8A8B8" />
        </linearGradient>
        <linearGradient id={trailId} x1="0.1" y1="0.1" x2="0.9" y2="0.9">
          <stop offset="0" stopColor="#C9C9D6" stopOpacity="0.08" />
          <stop offset="0.55" stopColor="#D8D8E2" stopOpacity="0.4" />
          <stop offset="1" stopColor="#E8E8EF" stopOpacity="0.6" />
        </linearGradient>
      </defs>
      <rect width="512" height="512" rx="104" fill={`url(#${backgroundId})`} />
      <g fill="none" stroke={`url(#${glyphId})`} strokeWidth="66" strokeLinecap="round">
        {/* 竖笔带轻微弓形，上端偏右、下端偏左，形成前倾动势 */}
        <path d="M214 112 C 194 200, 190 266, 204 366" />
        {/* 上臂上扬 */}
        <path d="M208 258 C 280 240, 340 196, 392 128" />
        {/* 下臂下沉，末端收在右下 */}
        <path d="M208 262 C 284 284, 344 326, 400 360" />
      </g>
      {/* 流线尾迹：承接下臂末端，向左侧渐隐 */}
      <path
        d="M206 408 C 276 426, 340 418, 396 386"
        fill="none"
        stroke={`url(#${trailId})`}
        strokeWidth="26"
        strokeLinecap="round"
      />
    </svg>
  );
}
