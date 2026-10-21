require 'rails_helper'

RSpec.describe MetricsAggregator do
  describe '.storage_metrics' do
    subject(:average) { described_class.storage_metrics[:average_usage_percent] }

    it 'returns 0 when there are no quotas' do
      expect(average).to eq(0)
    end

    it 'averages usage percentage across quotas' do
      create(:storage_quota, quota_bytes: 100, used_bytes: 25)
      create(:storage_quota, quota_bytes: 200, used_bytes: 150)

      expect(average).to eq(50.0)
    end

    it 'rounds the average to two decimals' do
      create(:storage_quota, quota_bytes: 3, used_bytes: 1)

      expect(average).to eq(33.33)
    end

    it 'aggregates allocated, used and over-quota totals' do
      create(:storage_quota, quota_bytes: 100, used_bytes: 25)
      create(:storage_quota, quota_bytes: 100, used_bytes: 120)

      metrics = described_class.storage_metrics
      expect(metrics[:total_allocated_bytes]).to eq(200)
      expect(metrics[:total_used_bytes]).to eq(145)
      expect(metrics[:users_over_quota]).to eq(1)
      expect(metrics[:by_tier]).to eq('free' => 2)
    end
  end
end
