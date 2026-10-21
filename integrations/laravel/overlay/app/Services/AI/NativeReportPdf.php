<?php

namespace App\Services\AI;

use RuntimeException;

/** A small, self-contained PDF writer for the read-only AI reports. */
final class NativeReportPdf
{
    private const WIDTH = 842;
    private const HEIGHT = 595;

    public static function canRender(array $texts): bool
    {
        foreach ($texts as $text) {
            if (is_array($text)) {
                if (! self::canRender($text)) {
                    return false;
                }
            } elseif ($text !== null && @iconv('UTF-8', 'Windows-1252', (string) $text) === false) {
                return false;
            }
        }

        return true;
    }

    public static function render(string $label, array $headings, array $values, ?string $status, string $generatedAt, string $logoPath): string
    {
        [$logoData, $logoWidth, $logoHeight] = self::png($logoPath);
        $pages = [];
        $commands = '';
        $y = 0;
        $page = function () use (&$pages, &$commands, &$y, $label, $status, $generatedAt, $values): void {
            if ($commands !== '') {
                $pages[] = $commands;
            }
            $commands = "q\n";
            self::rect($commands, 0, 0, self::WIDTH, self::HEIGHT, 'FFFFFF');
            self::rect($commands, 0, self::HEIGHT - 9, self::WIDTH, 9, 'E87722');
            $commands .= "q 56 0 0 46 42 512 cm /Logo Do Q\n";
            self::text($commands, 110, 550, 'LAPORAN RESMI HIREACH', 9, '536477', true);
            self::text($commands, 110, 527, 'Laporan '.$label, 20, '152238', true);
            self::line($commands, 42, 499, 800, 499, 'CBD5E1');
            self::text($commands, 43, 482, 'Jumlah data: '.number_format(count($values), 0, ',', '.').'   |   Status: '.($status ?: 'Semua status').'   |   Dibuat: '.$generatedAt, 9, '475569');
            self::text($commands, 43, 461, 'RINCIAN DATA', 10, '152238', true);
            $y = 445;
        };
        $page();

        if ($values === []) {
            self::text($commands, 44, $y - 14, 'Tidak ada data yang cocok dengan laporan ini.', 10, '64748B');
        }
        foreach ($values as $index => $row) {
            $linesByField = [];
            foreach ($headings as $column => $heading) {
                $value = $row[$column] ?? null;
                $display = is_bool($value) ? ($value ? 'Ya' : 'Tidak') : (is_scalar($value) ? (string) $value : json_encode($value, JSON_UNESCAPED_UNICODE));
                if ($display === '' || $display === null) {
                    $display = '-';
                }
                if ($heading === 'Aktif' && in_array($display, ['0', '1'], true)) {
                    $display = $display === '1' ? 'Ya' : 'Tidak';
                }
                $linesByField[] = self::wrap($heading.': '.$display, 122);
            }
            $recordHeight = 39 + array_sum(array_map(static fn (array $lines) => count($lines) * 12, $linesByField));
            if ($y < 445 && $y - $recordHeight < 55) {
                $page();
            }
            self::rect($commands, 42, $y - 23, 758, 25, $index % 2 === 0 ? 'F1F5F9' : 'F8FAFC');
            self::text($commands, 50, $y - 15, 'DATA '.($index + 1), 9, '152238', true);
            $y -= 31;
            foreach ($linesByField as $wrapped) {
                foreach ($wrapped as $line) {
                    if ($y < 61) {
                        $page();
                        self::text($commands, 50, $y - 10, 'DATA '.($index + 1).' (lanjutan)', 9, '152238', true);
                        $y -= 24;
                    }
                    self::text($commands, 54, $y, $line, 8.5, '334155');
                    $y -= 12;
                }
            }
            $y -= 8;
        }
        $pages[] = $commands;

        $objects = [];
        $add = static function (string $content) use (&$objects): int {
            $objects[] = $content;
            return count($objects);
        };
        $catalog = $add('');
        $tree = $add('');
        $regular = $add('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>');
        $bold = $add('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>');
        $logo = $add('<< /Type /XObject /Subtype /Image /Width '.$logoWidth.' /Height '.$logoHeight.' /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /DecodeParms << /Predictor 15 /Colors 3 /BitsPerComponent 8 /Columns '.$logoWidth.' >> /Length '.strlen($logoData).' >>'."\nstream\n".$logoData."\nendstream");
        $pageIds = [];
        foreach ($pages as $index => $body) {
            $body .= "Q\n";
            self::line($body, 42, 42, 800, 42, 'CBD5E1');
            self::text($body, 43, 27, 'HiReach | Laporan dibuat otomatis dari data akun yang sedang login.', 8, '64748B');
            self::text($body, 744, 27, 'Halaman '.($index + 1).' / '.count($pages), 8, '64748B');
            $stream = $add('<< /Length '.strlen($body).' >>'."\nstream\n".$body."endstream");
            $pageIds[] = $add('<< /Type /Page /Parent '.$tree.' 0 R /MediaBox [0 0 '.self::WIDTH.' '.self::HEIGHT.'] /Resources << /Font << /F1 '.$regular.' 0 R /F2 '.$bold.' 0 R >> /XObject << /Logo '.$logo.' 0 R >> >> /Contents '.$stream.' 0 R >>');
        }
        $objects[$tree - 1] = '<< /Type /Pages /Kids ['.implode(' ', array_map(static fn ($id) => $id.' 0 R', $pageIds)).'] /Count '.count($pageIds).' >>';
        $objects[$catalog - 1] = '<< /Type /Catalog /Pages '.$tree.' 0 R >>';
        $pdf = "%PDF-1.4\n%\xE2\xE3\xCF\xD3\n";
        $offsets = [0];
        foreach ($objects as $index => $object) {
            $offsets[] = strlen($pdf);
            $pdf .= ($index + 1)." 0 obj\n".$object."\nendobj\n";
        }
        $xref = strlen($pdf);
        $pdf .= 'xref'."\n0 ".(count($objects) + 1)."\n0000000000 65535 f \n";
        foreach (array_slice($offsets, 1) as $offset) {
            $pdf .= sprintf('%010d 00000 n ', $offset)."\n";
        }
        return $pdf.'trailer'."\n".'<< /Size '.(count($objects) + 1).' /Root '.$catalog.' 0 R >>'."\nstartxref\n".$xref."\n%%EOF\n";
    }

    private static function png(string $path): array
    {
        $png = is_file($path) ? file_get_contents($path) : false;
        if (! is_string($png) || substr($png, 0, 8) !== "\x89PNG\r\n\x1a\n") {
            throw new RuntimeException('Logo HiReach tidak tersedia untuk laporan PDF.');
        }
        $width = $height = 0;
        $data = '';
        for ($offset = 8; $offset + 12 <= strlen($png); $offset += $length + 12) {
            $length = unpack('N', substr($png, $offset, 4))[1];
            $type = substr($png, $offset + 4, 4);
            $chunk = substr($png, $offset + 8, $length);
            if ($type === 'IHDR') {
                [$width, $height] = array_values(unpack('N2', substr($chunk, 0, 8)));
                if (ord($chunk[8]) !== 8 || ord($chunk[9]) !== 2 || ord($chunk[12]) !== 0) {
                    throw new RuntimeException('Format logo HiReach tidak didukung.');
                }
            } elseif ($type === 'IDAT') {
                $data .= $chunk;
            } elseif ($type === 'IEND') {
                break;
            }
        }
        if ($width < 1 || $height < 1 || $data === '') {
            throw new RuntimeException('Logo HiReach tidak valid.');
        }
        return [$data, $width, $height];
    }

    private static function wrap(string $text, int $width): array
    {
        $text = preg_replace('/\s+/u', ' ', $text) ?? $text;
        preg_match_all('/.{1,'.$width.'}/us', $text, $matches);
        return $matches[0] ?: [''];
    }

    private static function text(string &$body, float $x, float $y, string $text, float $size, string $color, bool $bold = false): void
    {
        $encoded = @iconv('UTF-8', 'Windows-1252', $text);
        if ($encoded === false) {
            throw new RuntimeException('Teks laporan tidak dapat ditulis ke PDF bawaan. Gunakan preview untuk menyimpan PDF.');
        }
        $encoded = preg_replace('/[\x00-\x1F\x7F]/', ' ', $encoded) ?? '';
        $encoded = str_replace(['\\', '(', ')', "\r", "\n"], ['\\\\', '\\(', '\\)', ' ', ' '], $encoded);
        $body .= self::color($color)." BT /F".($bold ? '2' : '1').' '.$size.' Tf 1 0 0 1 '.$x.' '.$y.' Tm ('.$encoded.") Tj ET\n";
    }

    private static function rect(string &$body, float $x, float $y, float $width, float $height, string $color): void
    {
        $body .= self::color($color)." $x $y $width $height re f\n";
    }

    private static function line(string &$body, float $x1, float $y1, float $x2, float $y2, string $color): void
    {
        $body .= self::color($color)." $x1 $y1 m $x2 $y2 l S\n";
    }

    private static function color(string $hex): string
    {
        return sprintf('%.3f %.3f %.3f rg', hexdec(substr($hex, 0, 2)) / 255, hexdec(substr($hex, 2, 2)) / 255, hexdec(substr($hex, 4, 2)) / 255);
    }
}
