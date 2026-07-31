/** Client-side export helpers for table and chart blocks. */

function save(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function slug(title: string, fallback: string): string {
  const base = title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  return base || fallback;
}

export function toCsv(columns: string[], rows: (string | number)[][]): string {
  const cell = (v: string | number) => {
    const s = String(v).replace(/T00:00:00.*/, '');
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [columns.map(cell).join(','), ...rows.map((r) => r.map(cell).join(','))].join('\n');
}

export function downloadCsv(columns: string[], rows: (string | number)[][], name: string) {
  // The BOM is what makes Excel open a UTF-8 CSV without mangling accents.
  save(new Blob(['\ufeff', toCsv(columns, rows)], { type: 'text/csv;charset=utf-8' }),
    `${name}.csv`);
}

/**
 * Rasterise a rendered chart. Recharts draws an inline SVG, so it has to be serialised
 * and painted onto a canvas before the browser will hand back a PNG.
 */
export async function downloadSvgAsPng(svg: SVGSVGElement, name: string, scale = 2) {
  const { width, height } = svg.getBoundingClientRect();
  const clone = svg.cloneNode(true) as SVGSVGElement;
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  clone.setAttribute('width', String(width));
  clone.setAttribute('height', String(height));

  const source = new XMLSerializer().serializeToString(clone);
  const url = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(source)}`;

  const image = new Image();
  await new Promise((resolve, reject) => {
    image.onload = resolve;
    image.onerror = reject;
    image.src = url;
  });

  const canvas = document.createElement('canvas');
  canvas.width = width * scale;
  canvas.height = height * scale;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(image, 0, 0, canvas.width, canvas.height);

  canvas.toBlob((blob) => blob && save(blob, `${name}.png`), 'image/png');
}
