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
            if (! is_array($permissions) || ! is_array($permissions['_resources'] ?? null)) { return; }

            foreach ($permissions['_resources'] as &$resource) {
                if (! is_array($resource) || ! is_array($resource['fields'] ?? null)) { continue; }
                foreach (array_keys($resource['fields']) as $field) {
                    if (! is_string($field) || ! preg_match('/(?:^|_)(?:otp|pin|cvv|cvc|passport|iban|dob|ssn)(?:_|$)|(?:^|_)(?:verification|auth|security)_code(?:_|$)|(?:^|_)(?:card|account)_number(?:_|$)|(?:^|_)national_id(?:_|$)|(?:^|_)credit_card(?:_|$)/i', $field)) {
                        continue;
                    }
                    unset($resource['fields'][$field], $resource['filters'][$field]);
                    if (($resource['lookup'] ?? null) === $field) { $resource['lookup'] = null; }
                }
            }
            unset($resource);

            foreach (['blast_messages' => 'title', 'billing_users' => 'name'] as $key => $field) {
                $resource = &$permissions['_resources'][$key];
                if (is_array($resource) && empty($resource['lookup'])
                    && isset($resource['fields'][$field]) && str_starts_with($resource['fields'][$field], 'string')) {
                    $resource['lookup'] = $field;
                }
                unset($resource);
            }

            DB::table('ai_integrations')->where('id', $integration->id)
                ->update(['permissions' => json_encode($permissions)]);
        });
    }

    public function down(): void
    {
        // Keep administrator choices and protected fields as they stand after deployment.
    }
};
