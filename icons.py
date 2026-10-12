"""Lucide icon set for the UI: every emoji the interface uses is drawn as an
inline SVG line icon in the browser (see icon_head_html()). The emoji stay in
the Python strings - they are the stable token, and the readable fallback for
anything that is not a browser page (logs, PDF, screen-reader text).

Icons: Lucide (https://lucide.dev), ISC license:
  Copyright (c) for portions of Lucide are held by Cole Bemis 2013-2022 as part of
  Feather (MIT). All other copyright (c) for Lucide are held by Lucide Contributors 2022.
  Permission to use, copy, modify, and/or distribute this software for any purpose
  with or without fee is hereby granted, provided that the above copyright notice
  and this permission notice appear in all copies.
"""
import json

# Lucide SVG bodies (24x24 viewBox), only the icons the UI uses.
ICON_SVG = {
    'arrow-left': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m12 19l-7-7l7-7m7 7H5"/>',
    'backpack': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="M4 10a4 4 0 0 1 4-4h8a4 4 0 0 1 4 4v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2zm4 0h8m-8 8h8"/><path d="M8 22v-6a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v6M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/></g>',
    'book-open': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 5v16m8.001-2A2 2 0 0 0 22 17V5a2 2 0 0 0-1.999-2L16 3.002A5 5 0 0 0 12 5a5 5 0 0 0-4-2H4a2 2 0 0 0-2 2v12a2 2 0 0 0 1.999 2H8a5 5 0 0 1 4 2a5 5 0 0 1 4-2z"/>',
    'brain': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="M12 18V5m3 8a4.17 4.17 0 0 1-3-4a4.17 4.17 0 0 1-3 4m8.598-6.5A3 3 0 1 0 12 5a3 3 0 1 0-5.598 1.5"/><path d="M17.997 5.125a4 4 0 0 1 2.526 5.77"/><path d="M18 18a4 4 0 0 0 2-7.464"/><path d="M19.967 17.483A4 4 0 1 1 12 18a4 4 0 1 1-7.967-.517"/><path d="M6 18a4 4 0 0 1-2-7.464"/><path d="M6.003 5.125a4 4 0 0 0-2.526 5.77"/></g>',
    'building-2': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="M10 12h4m-4-4h4m0 13v-3a2 2 0 0 0-4 0v3"/><path d="M6 10H4a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-2"/><path d="M6 21V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v16"/></g>',
    'cassette-tape': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><rect width="20" height="16" x="2" y="4" rx="2"/><circle cx="8" cy="10" r="2"/><path d="M8 12h8"/><circle cx="16" cy="10" r="2"/><path d="m6 20l.7-2.9A1.4 1.4 0 0 1 8.1 16h7.8a1.4 1.4 0 0 1 1.4 1l.7 3"/></g>',
    'castle': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="M10 5V3m4 2V3m1 18v-3a3 3 0 0 0-6 0v3m9-18v8m0-6H6m16 6H2"/><path d="M22 9v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V9m4-6v8"/></g>',
    'check': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 6L9 17l-5-5"/>',
    'chevron-down': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m6 9l6 6l6-6"/>',
    'chevron-left': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m15 18l-6-6l6-6"/>',
    'chevron-right': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m9 18l6-6l-6-6"/>',
    'chevron-up': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m18 15l-6-6l-6 6"/>',
    'circle': '<circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"/>',
    'circle-check': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="m16 9l-5.5 5.5L8 12"/></g>',
    'circle-help': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3m.08 4h.01"/></g>',
    'circle-x': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="m15 9l-6 6m0-6l6 6"/></g>',
    'cloud-rain': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242M16 14v6m-8-6v6m4-4v6"/>',
    'cloud-sun': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 2v2m-7.07.93l1.41 1.41M20 12h2m-2.93-7.07l-1.41 1.41m-1.713 6.31a4 4 0 0 0-5.925-4.128M13 22H7a5 5 0 1 1 4.9-6H13a3 3 0 0 1 0 6"/>',
    'coffee': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 2v2m4-2v2m2 4a1 1 0 0 1 1 1v8a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4V9a1 1 0 0 1 1-1h14a4 4 0 1 1 0 8h-1M6 2v2"/>',
    'cpu': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="M12 20v2m0-20v2m5 16v2m0-20v2M2 12h2m-2 5h2M2 7h2m16 5h2m-2 5h2M20 7h2M7 20v2M7 2v2"/><rect width="16" height="16" x="4" y="4" rx="2"/><rect width="8" height="8" x="8" y="8" rx="1"/></g>',
    'crown': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11.562 3.266a.5.5 0 0 1 .876 0L15.39 8.87a1 1 0 0 0 1.516.294L21.183 5.5a.5.5 0 0 1 .798.519l-2.834 10.246a1 1 0 0 1-.956.734H5.81a1 1 0 0 1-.957-.734L2.02 6.02a.5.5 0 0 1 .798-.519l4.276 3.664a1 1 0 0 0 1.516-.294zM5 21h14"/>',
    'dices': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><rect width="12" height="12" x="2" y="10" rx="2" ry="2"/><path d="m17.92 14l3.5-3.5a2.24 2.24 0 0 0 0-3l-5-4.92a2.24 2.24 0 0 0-3 0L10 6M6 18h.01M10 14h.01M15 6h.01M18 9h.01"/></g>',
    'drama': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="M10 11h.01M14 6h.01M18 6h.01M6.5 13.1h.01M22 5c0 9-4 12-6 12s-6-3-6-12q0-3 6-3c6 0 6 1 6 3"/><path d="M17.4 9.9c-.8.8-2 .8-2.8 0m-4.5-2.8C9 7.2 7.7 7.7 6 8.6c-3.5 2-4.7 3.9-3.7 5.6c4.5 7.8 9.5 8.4 11.2 7.4c.9-.5 1.9-2.1 1.9-4.7"/><path d="M9.1 16.5c.3-1.1 1.4-1.7 2.4-1.4"/></g>',
    'eye': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="M2.062 12.348a1 1 0 0 1 0-.696a10.75 10.75 0 0 1 19.876 0a1 1 0 0 1 0 .696a10.75 10.75 0 0 1-19.876 0"/><circle cx="12" cy="12" r="3"/></g>',
    'eye-off': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="M10.733 5.076a10.744 10.744 0 0 1 11.205 6.575a1 1 0 0 1 0 .696a10.8 10.8 0 0 1-1.444 2.49m-6.41-.679a3 3 0 0 1-4.242-4.242"/><path d="M17.479 17.499a10.75 10.75 0 0 1-15.417-5.151a1 1 0 0 1 0-.696a10.75 10.75 0 0 1 4.446-5.143M2 2l20 20"/></g>',
    'feather': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.086 18.412A2 2 0 0 1 12.67 19H5v-7.672a2 2 0 0 1 .586-1.414L11.75 3.75a6 6 0 1 1 8.49 8.49zM16 8L2 22m15.488-7H9"/>',
    'fingerprint': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="M12 10a2 2 0 0 0-2 2c0 1.02-.1 2.51-.26 4M14 13.12c0 2.38 0 6.38-1 8.88m4.29-.98c.12-.6.43-2.3.5-3.02M2 12a10 10 0 0 1 18-6M2 16h.01m19.79 0c.2-2 .131-5.354 0-6"/><path d="M5 19.5C5.5 18 6 15 6 12a6 6 0 0 1 .34-2m2.31 12c.21-.66.45-1.32.57-2M9 6.8a6 6 0 0 1 9 5.2v2"/></g>',
    'flag': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 22V4a1 1 0 0 1 .4-.8A6 6 0 0 1 8 2c3 0 5 2 7.333 2q2 0 3.067-.8A1 1 0 0 1 20 4v10a1 1 0 0 1-.4.8A6 6 0 0 1 16 16c-3 0-5-2-8-2a6 6 0 0 0-4 1.528"/>',
    'flame': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3q1 4 4 6.5t3 5.5a1 1 0 0 1-14 0a5 5 0 0 1 1-3a1 1 0 0 0 5 0c0-2-1.5-3-1.5-5q0-2 2.5-4"/>',
    'flame-kindling': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 2c1 3 2.5 3.5 3.5 4.5A5 5 0 0 1 17 10a5 5 0 1 1-10 0c0-.3 0-.6.1-.9a2 2 0 1 0 3.3-2C8 4.5 11 2 12 2M5 22l14-4M5 18l14 4"/>',
    'flower-2': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="M12 5a3 3 0 1 1 3 3m-3-3a3 3 0 1 0-3 3m3-3v1M9 8a3 3 0 1 0 3 3M9 8h1m5 0a3 3 0 1 1-3 3m3-3h-1m-2 3v-1"/><circle cx="12" cy="8" r="2"/><path d="M12 10v12m0 0c4.2 0 7-1.667 7-5c-4.2 0-7 1.667-7 5m0 0c-4.2 0-7-1.667-7-5c4.2 0 7 1.667 7 5"/></g>',
    'folder-open': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m6 14l1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2"/>',
    'footprints': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v-2.38C4 11.5 2.97 10.5 3 8c.03-2.72 1.49-6 4.5-6C9.37 2 10 3.8 10 5.5c0 3.11-2 5.66-2 8.68V16a2 2 0 1 1-4 0m16 4v-2.38c0-2.12 1.03-3.12 1-5.62c-.03-2.72-1.49-6-4.5-6C14.63 6 14 7.8 14 9.5c0 3.11 2 5.66 2 8.68V20a2 2 0 1 0 4 0m-4-3h4M4 13h4"/>',
    'ghost': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 10v1m-7.472 9.472a1.6 1.6 0 0 1 2.277 0l1.057 1.056a1.6 1.6 0 0 0 2.276 0l1.057-1.056a1.6 1.6 0 0 1 2.277 0l1.114 1.114a1.4 1.4 0 0 0 2.414-1V10a8 8 0 0 0-16 0v10.586a1.4 1.4 0 0 0 2.414 1zM9 10v1"/>',
    'globe': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20a14.5 14.5 0 0 0 0-20M2 12h20"/></g>',
    'hand-fist': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="M12.035 17.012a3 3 0 0 0-3-3l-.311-.002a.72.72 0 0 1-.505-1.229l1.195-1.195A2 2 0 0 1 10.828 11H12a2 2 0 0 0 0-4H9.243a3 3 0 0 0-2.122.879l-2.707 2.707A4.83 4.83 0 0 0 3 14a8 8 0 0 0 8 8h2a8 8 0 0 0 8-8V7a2 2 0 1 0-4 0v2a2 2 0 1 0 4 0"/><path d="M13.888 9.662A2 2 0 0 0 17 8V5a2 2 0 1 0-4 0M9 5a2 2 0 1 0-4 0v5m4-3V4a2 2 0 1 1 4 0v3.268"/></g>',
    'hand-heart': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="M11 14h2a2 2 0 0 0 0-4h-3c-.6 0-1.1.2-1.4.6L3 16"/><path d="m14.45 13.39l5.05-4.694C20.196 8 21 6.85 21 5.75a2.75 2.75 0 0 0-4.797-1.837a.276.276 0 0 1-.406 0A2.75 2.75 0 0 0 11 5.75c0 1.2.802 2.248 1.5 2.946L16 11.95M2 15l6 6"/><path d="m7 20l1.6-1.4c.3-.4.8-.6 1.4-.6h4c1.1 0 2.1-.4 2.8-1.2l4.6-4.4a1 1 0 0 0-2.75-2.91"/></g>',
    'heart': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2 9.5a5.5 5.5 0 0 1 9.591-3.676a.56.56 0 0 0 .818 0A5.49 5.49 0 0 1 22 9.5c0 2.29-1.5 4-3 5.5l-5.492 5.313a2 2 0 0 1-3 .019L5 15c-1.5-1.5-3-3.2-3-5.5"/>',
    'heart-handshake': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19.414 14.414C21 12.828 22 11.5 22 9.5a5.5 5.5 0 0 0-9.591-3.676a.6.6 0 0 1-.818.001A5.5 5.5 0 0 0 2 9.5c0 2.3 1.5 4 3 5.5l5.535 5.362a2 2 0 0 0 2.879.052a2.12 2.12 0 0 0-.004-3a2.124 2.124 0 1 0 3-3a2.124 2.124 0 0 0 3.004 0a2 2 0 0 0 0-2.828l-1.881-1.882a2.41 2.41 0 0 0-3.409 0l-1.71 1.71a2 2 0 0 1-2.828 0a2 2 0 0 1 0-2.828l2.823-2.762"/>',
    'hourglass': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 22h14M5 2h14m-2 20v-4.172a2 2 0 0 0-.586-1.414L12 12l-4.414 4.414A2 2 0 0 0 7 17.828V22M7 2v4.172a2 2 0 0 0 .586 1.414L12 12l4.414-4.414A2 2 0 0 0 17 6.172V2"/>',
    'info': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4m0-4h.01"/></g>',
    'landmark': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 18v-7m1.119-8.795a2 2 0 0 1 1.762 0l7.84 3.846A.5.5 0 0 1 20.5 7h-17a.5.5 0 0 1-.22-.949zM14 18v-7m4 7v-7M3 22h18M6 18v-7"/>',
    'laugh': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M18 13a6 6 0 0 1-6 5a6 6 0 0 1-6-5zM9 9h.01M15 9h.01"/></g>',
    'leaf': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="M11 20a10 10 0 0 0 10-10a25.9 25.9 0 0 0-1.04-7.281a1 1 0 0 0-1.755-.325C15.833 5.5 13 5.5 9.8 6.1A7 7 0 0 0 11 20"/><path d="M2 21a5 5 0 0 1 2.911-4.544C7.613 15.212 8.351 15.24 11 13"/></g>',
    'library': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m16 6l4 14M12 6v14M8 8v12M4 4v16"/>',
    'lightbulb': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 14c.2-1 .7-1.7 1.5-2.5c1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5c.7.7 1.3 1.5 1.5 2.5m0 4h6m-5 4h4"/>',
    'lock': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></g>',
    'log-out': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m16 17l5-5l-5-5m5 5H9m0 9H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>',
    'map-pin': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="M20 10c0 4.993-5.539 10.193-7.399 11.799a1 1 0 0 1-1.202 0C9.539 20.193 4 14.993 4 10a8 8 0 0 1 16 0"/><circle cx="12" cy="10" r="3"/></g>',
    'megaphone': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="M11 6a13 13 0 0 0 8.4-2.8A1 1 0 0 1 21 4v12a1 1 0 0 1-1.6.8A13 13 0 0 0 11 14H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2z"/><path d="M6 14a12 12 0 0 0 2.4 7.2a2 2 0 0 0 3.2-2.4A8 8 0 0 1 10 14M8 6v8"/></g>',
    'menu': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 5h16M4 12h16M4 19h16"/>',
    'message-circle': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.992 16.342a2 2 0 0 1 .094 1.167l-1.065 3.29a1 1 0 0 0 1.236 1.168l3.413-.998a2 2 0 0 1 1.099.092a10 10 0 1 0-4.777-4.719"/>',
    'message-square-quote': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="M14 14a2 2 0 0 0 2-2V8h-2"/><path d="M22 17a2 2 0 0 1-2 2H6.828a2 2 0 0 0-1.414.586l-2.202 2.202A.71.71 0 0 1 2 21.286V5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2z"/><path d="M8 14a2 2 0 0 0 2-2V8H8"/></g>',
    'mic': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="M12 19v3m7-12v2a7 7 0 0 1-14 0v-2"/><rect width="6" height="13" x="9" y="2" rx="3"/></g>',
    'mic-vocal': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="m11 7.601l-5.994 8.19a1 1 0 0 0 .1 1.298l.817.818a1 1 0 0 0 1.314.087L15.09 12"/><path d="M16.5 21.174C15.5 20.5 14.372 20 13 20c-2.058 0-3.928 2.356-6 2s-2.775-3.369-1.5-4.5"/><circle cx="16" cy="7" r="5"/></g>',
    'minus': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 12h14"/>',
    'moon': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.985 12.486a9 9 0 1 1-9.473-9.472c.405-.022.617.46.402.803a6 6 0 0 0 8.268 8.268c.344-.215.825-.004.803.401"/>',
    'mountain': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m8 3l4 8l5-5l5 15H2z"/>',
    'mountain-snow': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="m8 3l4 8l5-5l5 15H2z"/><path d="M4.14 15.08q3.93-2.355 7.86.42c2.74 1.94 5.49 2 8.23.19"/></g>',
    'notebook-pen': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="M13.4 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-7.4M2 6h4m-4 4h4m-4 4h4m-4 4h4"/><path d="M21.378 5.626a1 1 0 1 0-3.004-3.004l-5.01 5.012a2 2 0 0 0-.506.854l-.837 2.87a.5.5 0 0 0 .62.62l2.87-.837a2 2 0 0 0 .854-.506z"/></g>',
    'orbit': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="M20.341 6.484A10 10 0 0 1 10.266 21.85m-6.607-4.334A10 10 0 0 1 13.74 2.152"/><circle cx="12" cy="12" r="3"/><circle cx="19" cy="5" r="2"/><circle cx="5" cy="19" r="2"/></g>',
    'palette': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="M12 22a1 1 0 0 1 0-20a10 9 0 0 1 10 9a5 5 0 0 1-5 5h-2.25a1.75 1.75 0 0 0-1.4 2.8l.3.4a1.75 1.75 0 0 1-1.4 2.8z"/><circle cx="13.5" cy="6.5" r=".5" fill="currentColor"/><circle cx="17.5" cy="10.5" r=".5" fill="currentColor"/><circle cx="6.5" cy="12.5" r=".5" fill="currentColor"/><circle cx="8.5" cy="7.5" r=".5" fill="currentColor"/></g>',
    'pause': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><rect width="5" height="18" x="14" y="3" rx="1"/><rect width="5" height="18" x="5" y="3" rx="1"/></g>',
    'pen-line': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 21h8m.174-14.188a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/>',
    'pencil': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497zM15 5l4 4"/>',
    'play': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.458l-12 7A2 2 0 0 1 5 19z"/>',
    'plus': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 12h14m-7-7v14"/>',
    'radiation': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 12h.01M14 15.464a4 4 0 0 1-4 0l-2.472 4.282a1 1 0 0 0 .465 1.416a10 10 0 0 0 8.014 0a1 1 0 0 0 .465-1.416zM16 12a4 4 0 0 0-2-3.464l2.472-4.282a1 1 0 0 1 1.46-.305a10 10 0 0 1 4.006 6.94A1 1 0 0 1 21 12zm-8 0a4 4 0 0 1 2-3.464L7.528 4.254a1 1 0 0 0-1.46-.305a10 10 0 0 0-4.006 6.94A1 1 0 0 0 3 12z"/>',
    'refresh-cw': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="M3 12a9 9 0 0 1 9-9a9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5m5 4a9 9 0 0 1-9 9a9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/></g>',
    'rocket': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09"/><path d="M9 12a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.4 22.4 0 0 1-4 2z"/><path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 .05 5 .05"/></g>',
    'save': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7M7 3v4a1 1 0 0 0 1 1h7"/></g>',
    'scale': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="M12 3v18m7-13l3 8a5 5 0 0 1-6 0zV7"/><path d="M3 7h1a17 17 0 0 0 8-2a17 17 0 0 0 8 2h1M5 8l3 8a5 5 0 0 1-6 0zV7m2 14h10"/></g>',
    'scroll-text': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="M15 12h-5m5-4h-5m9 9V5a2 2 0 0 0-2-2H4"/><path d="M8 21h12a2 2 0 0 0 2-2v-1a1 1 0 0 0-1-1H11a1 1 0 0 0-1 1v1a2 2 0 1 1-4 0V5a2 2 0 1 0-4 0v2a1 1 0 0 0 1 1h3"/></g>',
    'search': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="m21 21l-4.34-4.34"/><circle cx="11" cy="11" r="8"/></g>',
    'send-horizontal': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3.714 3.048a.498.498 0 0 0-.683.627l2.843 7.627a2 2 0 0 1 0 1.396l-2.842 7.627a.498.498 0 0 0 .682.627l18-8.5a.5.5 0 0 0 0-.904zM6 12h16"/>',
    'settings': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="M9.671 4.136a2.34 2.34 0 0 1 4.659 0a2.34 2.34 0 0 0 3.319 1.915a2.34 2.34 0 0 1 2.33 4.033a2.34 2.34 0 0 0 0 3.831a2.34 2.34 0 0 1-2.33 4.033a2.34 2.34 0 0 0-3.319 1.915a2.34 2.34 0 0 1-4.659 0a2.34 2.34 0 0 0-3.32-1.915a2.34 2.34 0 0 1-2.33-4.033a2.34 2.34 0 0 0 0-3.831A2.34 2.34 0 0 1 6.35 6.051a2.34 2.34 0 0 0 3.319-1.915"/><circle cx="12" cy="12" r="3"/></g>',
    'shield': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>',
    'skull': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="m12.5 17l-.5-1l-.5 1z"/><path d="M15 22a1 1 0 0 0 1-1v-1a2 2 0 0 0 1.56-3.25a8 8 0 1 0-11.12 0A2 2 0 0 0 8 20v1a1 1 0 0 0 1 1z"/><circle cx="15" cy="12" r="1"/><circle cx="9" cy="12" r="1"/></g>',
    'sliders-horizontal': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 5H3m9 14H3M14 3v4m2 10v4m5-9h-9m9 7h-5m5-14h-7m-6 5v4m0-2H3"/>',
    'smile': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2s4-2 4-2M9 9h.01M15 9h.01"/></g>',
    'spade': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 18v4M2 14.499a5.5 5.5 0 0 0 9.591 3.675a.6.6 0 0 1 .818.001A5.5 5.5 0 0 0 22 14.5c0-2.29-1.5-4-3-5.5l-5.492-5.312a2 2 0 0 0-3-.02L5 8.999c-1.5 1.5-3 3.2-3 5.5"/>',
    'sparkle': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11.017 2.814a1 1 0 0 1 1.966 0l1.051 5.558a2 2 0 0 0 1.594 1.594l5.558 1.051a1 1 0 0 1 0 1.966l-5.558 1.051a2 2 0 0 0-1.594 1.594l-1.051 5.558a1 1 0 0 1-1.966 0l-1.051-5.558a2 2 0 0 0-1.594-1.594l-5.558-1.051a1 1 0 0 1 0-1.966l5.558-1.051a2 2 0 0 0 1.594-1.594z"/>',
    'sparkles': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="M11.017 2.814a1 1 0 0 1 1.966 0l1.051 5.558a2 2 0 0 0 1.594 1.594l5.558 1.051a1 1 0 0 1 0 1.966l-5.558 1.051a2 2 0 0 0-1.594 1.594l-1.051 5.558a1 1 0 0 1-1.966 0l-1.051-5.558a2 2 0 0 0-1.594-1.594l-5.558-1.051a1 1 0 0 1 0-1.966l5.558-1.051a2 2 0 0 0 1.594-1.594zM20 2v4m2-2h-4"/><circle cx="4" cy="20" r="2"/></g>',
    'split': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="M16 3h5v5M8 3H3v5"/><path d="M12 22v-8.3a4 4 0 0 0-1.172-2.872L3 3m12 6l6-6"/></g>',
    'square': '<rect width="18" height="18" x="3" y="3" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" rx="2"/>',
    'star': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.12 2.12 0 0 0 1.595 1.16l5.166.756a.53.53 0 0 1 .294.904l-3.736 3.638a2.12 2.12 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 1-.771.56l-4.618-2.428a2.12 2.12 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.12 2.12 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755a2.12 2.12 0 0 0 1.597-1.16z"/>',
    'sword': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m11 19l-6-6m0 8l-2-2m5-3l-4 4m5.5-2.5L20.414 6.586A2 2 0 0 0 21 5.172V3h-2.172a2 2 0 0 0-1.414.586L6.5 14.5"/>',
    'swords': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m13 19l6-6m-4.5 4.5L3.586 6.586A2 2 0 0 1 3 5.172V3h2.172a2 2 0 0 1 1.414.586L17.5 14.5m-2.672-8.328l2.586-2.586A2 2 0 0 1 18.828 3H21v2.172a2 2 0 0 1-.586 1.414l-2.586 2.586M16 16l4 4m-1 1l2-2M5 14l4 4m-4 3l-2-2m4.5-2.5L4 20"/>',
    'tent-tree': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><circle cx="4" cy="4" r="2"/><path d="m14 5l3-3l3 3m-6 5l3-3l3 3m-3 4V2m0 12H7l-5 8h20Zm-9 0v8m1-8l5 8"/></g>',
    'theater': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="M2 10s3-3 3-8m17 8s-3-3-3-8"/><path d="M10 2c0 4.4-3.6 8-8 8m12-8c0 4.4 3.6 8 8 8M2 10s2 2 2 5m18-5s-2 2-2 5M8 15h8M2 22v-1a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v1m4 0v-1a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v1"/></g>',
    'tornado': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 4H3m15 4H6m13 4H9m7 4h-6m1 4H9"/>',
    'trash-2': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 11v6m4-6v6m5-11v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
    'triangle-alert': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m21.73 18l-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3M12 9v4m0 4h.01"/>',
    'user-minus': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 11h-6"/></g>',
    'user-plus': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M19 8v6m3-3h-6"/></g>',
    'user-round': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><circle cx="12" cy="8" r="5"/><path d="M20 21a8 8 0 0 0-16 0"/></g>',
    'users': '<g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M16 3.128a4 4 0 0 1 0 7.744M22 21v-2a4 4 0 0 0-3-3.87"/><circle cx="9" cy="7" r="4"/></g>',
    'wand-sparkles': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m21.64 3.64l-1.28-1.28a1.21 1.21 0 0 0-1.72 0L2.36 18.64a1.21 1.21 0 0 0 0 1.72l1.28 1.28a1.2 1.2 0 0 0 1.72 0L21.64 5.36a1.2 1.2 0 0 0 0-1.72M14 7l3 3M5 6v4m14 4v4M10 2v2M7 8H3m18 8h-4M11 3H9"/>',
    'wrench': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.106-3.105c.32-.322.863-.22.983.218a6 6 0 0 1-8.259 7.057l-7.91 7.91a1 1 0 0 1-2.999-3l7.91-7.91a6 6 0 0 1 7.057-8.259c.438.12.54.662.219.984z"/>',
    'x': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M18 6L6 18M6 6l12 12"/>',
    'zap': '<path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.914 4a1.5 1.5 0 0 0-2.474-1.561l-9 9A1.5 1.5 0 0 0 5.5 14h4.002a.5.5 0 0 1 .471.666L8.086 20a1.5 1.5 0 0 0 2.475 1.56l9-9A1.5 1.5 0 0 0 18.5 10h-3.997a.5.5 0 0 1-.472-.667z"/>',
}

# Emoji (without the U+FE0F variation selector) -> Lucide icon name.
# Every emoji used in the UI needs an entry here (tests/test_icons.py).
EMOJI_ICON = {
    "\u2764": 'heart',
    "\U0001f499": 'sparkle',
    "\U0001f392": 'backpack',
    "\U0001f32a": 'tornado',
    "\u23f0": 'hourglass',
    "\U0001f4d6": 'book-open',
    "\U0001f465": 'users',
    "\U0001f4cd": 'map-pin',
    "\U0001f464": 'user-round',
    "\u25b6": 'play',
    "\u2728": 'sparkles',
    "\u2b50": 'star',
    "\U0001f525": 'flame',
    "\U0001f480": 'skull',
    "\u26a1": 'zap',
    "\u2604": 'orbit',
    "\U0001f3b2": 'dices',
    "\U0001f4dc": 'scroll-text',
    "\u2694": 'swords',
    "\U0001f6e1": 'shield',
    "\U0001f311": 'moon',
    "\U0001fab6": 'feather',
    "\U0001f4a1": 'lightbulb',
    "\U0001f9e0": 'brain',
    "\U0001f91d": 'heart-handshake',
    "\U0001f49a": 'heart',
    "\U0001f49b": 'heart',
    "\U0001f5a4": 'moon',
    "\u2705": 'circle-check',
    "\u26a0": 'triangle-alert',
    "\u274c": 'circle-x',
    "\U0001f4be": 'save',
    "\U0001f4c2": 'folder-open',
    "\U0001f5d1": 'trash-2',
    "\U0001f504": 'refresh-cw',
    "\u2699": 'settings',
    "\u2795": 'plus',
    "\u2753": 'circle-help',
    "\U0001f30d": 'globe',
    "\u270d": 'pen-line',
    "\u270e": 'pencil',
    "\U0001f399": 'mic',
    "\U0001f3a4": 'mic-vocal',
    "\U0001f3c1": 'flag',
    "\U0001f50d": 'search',
    "\U0001f4ac": 'message-circle',
    "\U0001f4da": 'library',
    "\U0001f3f0": 'castle',
    "\U0001fa84": 'wand-sparkles',
    "\U0001f680": 'rocket',
    "\U0001f47b": 'ghost',
    "\U0001f52e": 'eye',
    "\U0001f306": 'cpu',
    "\U0001f3d9": 'building-2',
    "\U0001f575": 'fingerprint',
    "\U0001f3db": 'landmark',
    "\U0001f451": 'crown',
    "\U0001f4fc": 'cassette-tape',
    "\u26fa": 'tent-tree',
    "\u2622": 'radiation',
    "\u2696": 'scale',
    "\U0001f327": 'cloud-rain',
    "\U0001f317": 'cloud-rain',
    "\U0001f56f": 'flame-kindling',
    "\U0001f60a": 'smile',
    "\U0001f606": 'laugh',
    "\U0001f3d4": 'mountain-snow',
    "\U0001f4a5": 'zap',
    "\u2615": 'coffee',
    "\U0001f3ad": 'drama',
    "\U0001f628": 'ghost',
    "\U0001f343": 'leaf',
    "\U0001f338": 'flower-2',
    "\U0001f463": 'footprints',
    "\u2660": 'spade',
    "\u270a": 'hand-fist',
    "\U0001faf6": 'hand-heart',
    "\U0001f527": 'wrench',
    "\U0001f3a8": 'palette',
    "\U0001f5e1": 'sword',
}

# Coloured circle emoji become small colour dots (disposition, position, clock type).
DOT_COLORS = {
    "\U0001f534": '#ef4444',
    "\U0001f7e0": '#f59e0b',
    "\u26aa": '#a3a3a3',
    "\U0001f7e2": '#4ade80',
    "\U0001f7e3": '#a78bfa',
    "\U0001f7e1": '#facc15',
}

# Quasar/Material icon ligatures (ui.button(icon=...), ui.icon(...), Quasar internals
# such as the expansion arrow) -> Lucide icon name. The ligature text stays in
# the <i> element (invisible, keeps the size); the SVG is laid over it.
MATERIAL_ICON = {
    'menu': 'menu',
    'chevron_left': 'chevron-left',
    'chevron_right': 'chevron-right',
    'mic': 'mic',
    'stop': 'square',
    'send': 'send-horizontal',
    'play_arrow': 'play',
    'refresh': 'refresh-cw',
    'arrow_back': 'arrow-left',
    'delete_outline': 'trash-2',
    'delete': 'trash-2',
    'info_outline': 'info',
    'info': 'info',
    'close': 'x',
    'clear': 'x',
    'cancel': 'circle-x',
    'groups': 'users',
    'tune': 'sliders-horizontal',
    'pause': 'pause',
    'person': 'user-round',
    'person_add': 'user-plus',
    'person_remove': 'user-minus',
    'logout': 'log-out',
    'theater_comedy': 'theater',
    'edit_note': 'notebook-pen',
    'record_voice_over': 'message-square-quote',
    'bolt': 'zap',
    'search': 'search',
    'hourglass_top': 'hourglass',
    'local_cafe': 'coffee',
    'priority_high': 'mountain',
    'visibility_off': 'eye-off',
    'campaign': 'megaphone',
    'lock': 'lock',
    'alt_route': 'split',
    'cloud': 'cloud-sun',
    'radio_button_unchecked': 'circle',
    'keyboard_arrow_down': 'chevron-down',
    'keyboard_arrow_up': 'chevron-up',
    'expand_more': 'chevron-down',
    'expand_less': 'chevron-up',
    'arrow_drop_down': 'chevron-down',
    'arrow_drop_up': 'chevron-up',
    'warning': 'triangle-alert',
    'error': 'circle-x',
    'check_circle': 'circle-check',
    'check': 'check',
    'done': 'check',
    'visibility': 'eye',
    'add': 'plus',
    'remove': 'minus',
    'edit': 'pencil',
}

# Characters that stay as text: they already match the UI font.
TYPOGRAPHIC = {"\u2192", "\u2713", "\u00B7", "\u2014", "\u2013", "\u2500"}


_ICON_CSS = """
.et-ic { display:inline-block; width:1.08em; height:1.08em; vertical-align:-0.17em;
         margin-right:0.36em; flex-shrink:0; color:inherit; }
.et-ic.et-end { margin-right:0; }
.et-ic svg { display:block; width:100%; height:100%; }
.et-ic svg * { stroke-width:1.75; }
.et-dot { display:inline-block; width:0.55em; height:0.55em; border-radius:50%;
          margin:0 0.5em 0.08em 0.1em; vertical-align:middle; flex-shrink:0; }
.et-dot.et-end { margin-right:0; }
.q-expansion-item .q-item__label > .et-ic, .q-drawer .text-sm.font-semibold > .et-ic { color:var(--text-secondary); }
/* colour only where it carries meaning */
.q-drawer .track-label.health > .et-ic, .track-label.health .et-ic { color:#ef4444; }
.q-drawer .track-label.spirit > .et-ic, .track-label.spirit .et-ic { color:#60a5fa; }
.q-drawer .track-label.supply > .et-ic, .track-label.supply .et-ic { color:var(--accent-light); }
.q-drawer .track-label.chaos > .et-ic,  .track-label.chaos  .et-ic { color:#c98f85; }
i.material-icons.et-mi { position:relative; -webkit-text-fill-color:transparent; }
i.material-icons.et-mi > svg { position:absolute; inset:0; width:100%; height:100%;
                              -webkit-text-fill-color:initial; pointer-events:none; }
i.material-icons.et-mi > svg * { stroke-width:1.9; }
.choice-btn .et-ic { width:1.22em; height:1.22em; vertical-align:-0.24em; margin-right:0.45em; color:var(--accent-light); }
"""

# Runs in the browser. Vue owns the text nodes it renders and may later write a
# new value into the SAME node (nodeValue) - so the original node is never
# replaced: it keeps the text before the first emoji, and the icons plus the rest
# of the text follow as own sibling elements (data-et-own). When Vue rewrites
# the node, the own siblings are dropped and rebuilt from the new text.
_ICON_JS = r"""
(function(){
  var D = __DATA__;
  var keys = Object.keys(D.icons).concat(Object.keys(D.dots)).sort(function(a,b){return b.length-a.length;});
  var RE = new RegExp('(' + keys.map(function(k){return k.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');}).join('|') + ')️?', 'g');
  var SKIP = 'input,textarea,script,style,svg,[contenteditable],[data-et-own]';
  function hasEmoji(v){ RE.lastIndex = 0; return RE.test(v); }
  function dropOwn(t){
    var n = t.nextSibling;
    while (n && n.nodeType === 1 && n.hasAttribute('data-et-own')) { var x = n.nextSibling; n.remove(); n = x; }
  }
  function mark(e, atEnd){
    var sp = document.createElement('span');
    sp.setAttribute('data-et-own', ''); sp.setAttribute('aria-hidden', 'true');
    if (D.dots[e]) { sp.className = 'et-dot'; sp.style.background = D.dots[e]; }
    else { sp.className = 'et-ic'; sp.innerHTML = D.svg[D.icons[e]]; }
    if (atEnd) sp.className += ' et-end';
    return sp;
  }
  function text(s){
    var sp = document.createElement('span'); sp.setAttribute('data-et-own', ''); sp.textContent = s; return sp;
  }
  function swap(t){
    var v = t.nodeValue;
    if (t.__etSet !== undefined && v === t.__etSet) return;        // our own write
    if (!hasEmoji(v)) { if (t.__etSet !== undefined) { dropOwn(t); t.__etSet = undefined; } return; }
    var p = t.parentNode; if (!p || (p.closest && p.closest(SKIP))) return;
    dropOwn(t);
    var parts = [], last = 0, m; RE.lastIndex = 0;
    while ((m = RE.exec(v))) {
      parts.push(v.slice(last, m.index));
      var after = v.slice(m.index + m[0].length);
      var atEnd = !after.trim();
      parts.push(mark(m[1], atEnd));
      last = m.index + m[0].length;
      if (!atEnd && v.charAt(last) === ' ') last++;               // icon margin replaces the space
    }
    parts.push(v.slice(last));
    var frag = document.createDocumentFragment();
    for (var i = 1; i < parts.length; i++) {
      var x = parts[i];
      if (typeof x === 'string') { if (x) frag.appendChild(text(x)); } else frag.appendChild(x);
    }
    t.__etSet = parts[0];
    t.nodeValue = parts[0];
    p.insertBefore(frag, t.nextSibling);
  }
  // Material ligature icons: keep Quasar's <i> and its text, lay a Lucide SVG over it
  function mi(el){
    var name = '';
    el.childNodes.forEach(function(c){ if (c.nodeType === 3) name += c.nodeValue; });
    name = name.trim();
    var old = el.querySelector(':scope > svg[data-et-own]');
    var want = D.mi[name];
    if (old && old.getAttribute('data-et-mi') === want) return;
    if (old) old.remove();
    if (!want) { el.classList.remove('et-mi'); return; }
    var tmp = document.createElement('span'); tmp.innerHTML = D.svg[want];
    var svg = tmp.firstChild; svg.setAttribute('data-et-own', ''); svg.setAttribute('data-et-mi', want);
    el.appendChild(svg); el.classList.add('et-mi');
  }
  function scanMi(root){
    if (root.nodeType !== 1) return;
    if (root.matches && root.matches('i.material-icons')) mi(root);
    if (root.querySelectorAll) root.querySelectorAll('i.material-icons').forEach(mi);
  }
  function scan(root){
    if (root.nodeType === 3) { swap(root); return; }
    scanMi(root);
    if (root.nodeType !== 1 || (root.closest && root.closest(SKIP))) return;
    var w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT), n, list = [];
    while ((n = w.nextNode())) list.push(n);
    list.forEach(swap);
  }
  var obs = new MutationObserver(function(muts){
    muts.forEach(function(mu){
      var t = mu.target, host = (t.nodeType === 1 ? t : t.parentElement);
      if (host && host.matches && host.matches('i.material-icons')) { mi(host); return; }
      if (mu.type === 'characterData') swap(t);
      else mu.addedNodes.forEach(scan);
    });
  });
  function start(){ scan(document.body);
    obs.observe(document.body, {childList:true, subtree:true, characterData:true}); }
  if (document.body) start(); else document.addEventListener('DOMContentLoaded', start);
})();
"""


def icon_head_html() -> str:
    """<style> + <script> that draw every UI emoji and Material icon as a Lucide line icon."""
    data = {"icons": EMOJI_ICON, "dots": DOT_COLORS, "mi": MATERIAL_ICON,
            "svg": {n: f'<svg viewBox="0 0 24 24" aria-hidden="true">{b}</svg>'
                    for n, b in ICON_SVG.items()}}
    js = _ICON_JS.replace("__DATA__", json.dumps(data, ensure_ascii=False))
    return f"<style>{_ICON_CSS}</style>\n<script>{js}</script>\n"
