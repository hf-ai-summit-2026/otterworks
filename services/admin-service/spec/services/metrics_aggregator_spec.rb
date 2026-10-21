require 'rails_helper'

RSpec.describe MetricsAggregator do
  describe '.storage_metrics' do
    context 'when there are no storage quotas' do
      it 'returns zeroed metrics' do
        metrics = described_class.storage_metrics

        expect(metrics[:total_allocated_bytes]).to eq(0)
        expect(metrics[:total_used_bytes]).to eq(0)
        expect(metrics[:average_usage_percent]).to eq(0)
        expect(metrics[:users_over_quota]).to eq(0)
        expect(metrics[:by_tier]).to eq({})
      end
    end

    context 'with storage quotas' do
      before do
        create(:storage_quota, quota_bytes: 1_000, used_bytes: 250)
        create(:storage_quota, quota_bytes: 1_000, used_bytes: 1_500, tier: 'pro')
      end

      it 'aggregates totals, average usage and tiers' do
        metrics = described_class.storage_metrics

        expect(metrics[:total_allocated_bytes]).to eq(2_000)
        expect(metrics[:total_used_bytes]).to eq(1_750)
        expect(metrics[:average_usage_percent]).to eq(87.5)
        expect(metrics[:users_over_quota]).to eq(1)
        expect(metrics[:by_tier]).to eq('free' => 1, 'pro' => 1)
      end

      it 'computes the average without a separate COUNT query' do
        queries = []
        callback = ->(*, payload) { queries << payload[:sql] }
        ActiveSupport::Notifications.subscribed(callback, 'sql.active_record') do
          described_class.storage_metrics
        end

        expect(queries.grep(/SELECT COUNT\(\*\) FROM "storage_quotas"\z/)).to be_empty
      end
    end
  end

  describe '.summary' do
    it 'includes every metrics section' do
      expect(described_class.summary.keys)
        .to contain_exactly(:timestamp, :users, :storage, :features, :announcements, :audit)
    end
  end
end
