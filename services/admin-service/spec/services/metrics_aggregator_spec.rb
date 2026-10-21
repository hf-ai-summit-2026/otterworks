require 'rails_helper'

RSpec.describe MetricsAggregator do
  describe '.storage_metrics' do
    subject(:metrics) { described_class.storage_metrics }

    it 'reports zero average usage when there are no quotas' do
      expect(metrics[:average_usage_percent]).to eq(0)
    end

    it 'averages usage percentage across quotas' do
      create(:storage_quota, quota_bytes: 100, used_bytes: 25)
      create(:storage_quota, quota_bytes: 100, used_bytes: 75)

      expect(metrics[:average_usage_percent]).to eq(50.0)
    end

    it 'rounds the average usage to two decimal places' do
      create(:storage_quota, quota_bytes: 3, used_bytes: 1)

      expect(metrics[:average_usage_percent]).to eq(33.33)
    end

    it 'aggregates allocation, usage and over-quota counts' do
      create(:storage_quota, quota_bytes: 100, used_bytes: 40)
      create(:storage_quota, :pro, quota_bytes: 100, used_bytes: 150)

      expect(metrics).to include(
        total_allocated_bytes: 200,
        total_used_bytes: 190,
        users_over_quota: 1,
        by_tier: { 'free' => 1, 'pro' => 1 }
      )
    end
  end
end
