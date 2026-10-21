require 'rails_helper'

RSpec.describe MetricsAggregator do
  describe '.storage_metrics' do
    it 'reports zero average usage when there are no quotas' do
      expect(described_class.storage_metrics[:average_usage_percent]).to eq(0)
    end

    it 'reports zero average usage when every quota is zero bytes' do
      quota = create(:storage_quota, used_bytes: 0)
      quota.update_column(:quota_bytes, 0)

      expect(described_class.storage_metrics[:average_usage_percent]).to eq(0)
    end

    it 'averages per-user usage percentages rounded to two decimals' do
      create(:storage_quota, quota_bytes: 100, used_bytes: 25)
      create(:storage_quota, quota_bytes: 300, used_bytes: 100)

      expect(described_class.storage_metrics[:average_usage_percent]).to eq(29.17)
    end

    it 'aggregates totals, over-quota count and tier breakdown' do
      create(:storage_quota, quota_bytes: 100, used_bytes: 50, tier: 'free')
      create(:storage_quota, quota_bytes: 100, used_bytes: 150, tier: 'pro')

      metrics = described_class.storage_metrics

      expect(metrics).to include(
        total_allocated_bytes: 200,
        total_used_bytes: 200,
        users_over_quota: 1,
        by_tier: { 'free' => 1, 'pro' => 1 }
      )
    end
  end
end
