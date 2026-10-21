<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    public function up(): void
    {
        if (! Schema::hasTable('ai_integrations')) { return; }

        DB::transaction(function () {
            $integration = DB::table('ai_integrations')->orderByDesc('id')->lockForUpdate()->first();
            if (! $integration) { return; }

            $permissions = json_decode($integration->permissions ?? '{}', true);
            if (! is_array($permissions)) { return; }
            $blast = $permissions['_resources']['blast_messages'] ?? null;
            if (! is_array($blast) || ! isset($blast['fields']['status'])
                || ! str_starts_with($blast['fields']['status'], 'string')
                || ! empty($blast['filters']['status'])) { return; }

            $permissions['_resources']['blast_messages']['filters']['status'] = ['SUCCESS', 'FAILED'];
            DB::table('ai_integrations')->where('id', $integration->id)
                ->update(['permissions' => json_encode($permissions)]);
        });
    }

    public function down(): void
    {
        // Keep any filter choices subsequently edited by an administrator.
    }
};
