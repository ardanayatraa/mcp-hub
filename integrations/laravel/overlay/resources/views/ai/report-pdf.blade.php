<!doctype html>
<html lang="id">
<head>
    <meta charset="utf-8">
    <title>Laporan {{ $label }} - HiReach</title>
    <style>
        @page { margin: 32px 38px 54px; }
        body { margin: 0; font-family: DejaVu Sans, sans-serif; font-size: 9px; color: #1f2937; }
        .masthead { width: 100%; border-bottom: 2px solid #1e293b; padding-bottom: 12px; margin-bottom: 17px; }
        .masthead td { vertical-align: middle; }
        .logo { width: 80px; height: auto; }
        .brand { text-align: right; }
        .eyebrow { color: #64748b; font-size: 8px; font-weight: bold; letter-spacing: 1.4px; text-transform: uppercase; }
        h1 { margin: 4px 0 5px; color: #0f172a; font-size: 20px; line-height: 1.2; }
        .subtitle { color: #475569; font-size: 9px; }
        .summary { width: 100%; border-collapse: collapse; margin: 0 0 19px; }
        .summary td { width: 33%; padding: 10px 13px; background: #f1f5f9; border-right: 4px solid #fff; vertical-align: top; }
        .summary .label { display: block; color: #64748b; font-size: 8px; margin-bottom: 5px; }
        .summary .value { display: block; color: #0f172a; font-size: 11px; font-weight: bold; }
        h2 { color: #0f172a; font-size: 12px; margin: 0 0 8px; }
        .report-table { width: 100%; border-collapse: collapse; table-layout: fixed; }
        .report-table thead { display: table-header-group; }
        .report-table tr { page-break-inside: avoid; }
        .report-table th { background: #1e293b; color: #fff; text-align: left; padding: 8px 7px; font-size: 8px; }
        .report-table td { border-bottom: 1px solid #e2e8f0; padding: 7px; vertical-align: top; overflow-wrap: anywhere; }
        .report-table tbody tr:nth-child(even) td { background: #f8fafc; }
        .number { width: 32px; color: #64748b; }
        .record { border: 1px solid #cbd5e1; margin: 0 0 10px; page-break-inside: avoid; }
        .record-head { background: #f1f5f9; border-bottom: 1px solid #cbd5e1; padding: 7px 10px; font-weight: bold; color: #0f172a; }
        .record table { width: 100%; border-collapse: collapse; }
        .record td { width: 50%; padding: 6px 10px; vertical-align: top; border-bottom: 1px solid #edf2f7; overflow-wrap: anywhere; }
        .record .field { color: #64748b; font-size: 8px; display: block; margin-bottom: 2px; }
        .empty { padding: 20px; background: #f8fafc; border: 1px solid #e2e8f0; color: #64748b; }
        .footer { position: fixed; bottom: -37px; left: 0; right: 0; border-top: 1px solid #cbd5e1; padding-top: 8px; color: #64748b; font-size: 8px; }
        .preview-toolbar { display: none; }
        @media screen {
            body { max-width: 1120px; margin: 24px auto; padding: 30px; background: #fff; box-shadow: 0 8px 32px #0001; font-size: 12px; }
            html { background: #f1f5f9; }
            .logo { width: 100px; }
            .report-table th, .report-table td { font-size: 11px; }
            .preview-toolbar { display: flex; align-items: center; gap: 12px; margin: -20px 0 24px; padding: 12px; background: #eaf2ff; border-radius: 8px; font-family: Arial, sans-serif; }
            .preview-toolbar strong { margin-right: auto; font-size: 14px; }
            .preview-toolbar a, .preview-toolbar button { border: 0; border-radius: 6px; padding: 9px 14px; background: #1e293b; color: white; text-decoration: none; font-size: 12px; cursor: pointer; }
            .preview-toolbar button { background: #e87722; }
            .footer { position: static; margin-top: 28px; }
        }
        @media print { .preview-toolbar { display: none !important; } }
    </style>
</head>
<body>
@if ($preview ?? false)
    <div class="preview-toolbar">
        <strong>Preview laporan HiReach</strong>
        @if ($downloadUrl)<a href="{{ $downloadUrl }}">Unduh {{ $format === 'pdf' ? 'PDF' : 'Excel' }}</a>@endif
        <button type="button" id="print-report">Cetak / Simpan PDF</button>
    </div>
    <script src="{{ asset('js/ai-report-preview.js') }}" defer></script>
@endif
@php
    $display = static function ($value, string $heading = ''): string {
        if ($value === null || $value === '') { return '-'; }
        if ($heading === 'Aktif' && in_array((string) $value, ['0', '1'], true)) {
            return (string) $value === '1' ? 'Ya' : 'Tidak';
        }
        if (is_bool($value)) { return $value ? 'Ya' : 'Tidak'; }
        return is_scalar($value) ? (string) $value : (json_encode($value, JSON_UNESCAPED_UNICODE) ?: '-');
    };
@endphp
<table class="masthead"><tr>
    <td><img class="logo" src="{{ $logo }}" alt="HiReach"></td>
    <td class="brand">
        <div class="eyebrow">Laporan resmi HiReach</div>
        <h1>Laporan {{ $label }}</h1>
        <div class="subtitle">Data yang diizinkan untuk akun Anda</div>
    </td>
</tr></table>
<table class="summary"><tr>
    <td><span class="label">JUMLAH DATA</span><span class="value">{{ number_format(count($values), 0, ',', '.') }} data</span></td>
    <td><span class="label">FILTER STATUS</span><span class="value">{{ $status ?: 'Semua status' }}</span></td>
    <td><span class="label">DIBUAT PADA</span><span class="value">{{ $generatedAt }}</span></td>
</tr></table>
<h2>Rincian data</h2>
@if ($values === [])
    <div class="empty">Tidak ada data yang cocok dengan laporan ini.</div>
@elseif (count($headings) <= 6)
    <table class="report-table">
        <thead><tr><th class="number">No.</th>@foreach ($headings as $heading)<th>{{ $heading }}</th>@endforeach</tr></thead>
        <tbody>
        @foreach ($values as $index => $row)
            <tr><td class="number">{{ $index + 1 }}</td>@foreach ($row as $column => $value)<td>{{ $display($value, $headings[$column] ?? '') }}</td>@endforeach</tr>
        @endforeach
        </tbody>
    </table>
@else
    @foreach ($values as $index => $row)
        <div class="record">
            <div class="record-head">{{ $index + 1 }}. {{ $display($row[0] ?? null) }}</div>
            <table>
                @foreach (array_chunk($row, 2, true) as $pair)
                    <tr>
                        @foreach ($pair as $column => $value)
                            <td><span class="field">{{ $headings[$column] ?? 'Field' }}</span>{{ $display($value, $headings[$column] ?? '') }}</td>
                        @endforeach
                        @if (count($pair) === 1)<td></td>@endif
                    </tr>
                @endforeach
            </table>
        </div>
    @endforeach
@endif
<div class="footer">HiReach &nbsp;|&nbsp; Laporan dibuat otomatis dari data akun yang sedang login.</div>
</body>
</html>
