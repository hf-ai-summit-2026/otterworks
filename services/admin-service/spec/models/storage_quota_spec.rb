require 'rails_helper'

RSpec.describe StorageQuota do
  describe 'validations' do
    subject { build(:storage_quota) }

    it { is_expected.to validate_presence_of(:user_id) }
    it { is_expected.to validate_uniqueness_of(:user_id).case_insensitive }
    it { is_expected.to validate_presence_of(:quota_bytes) }
    it { is_expected.to validate_numericality_of(:quota_bytes).is_greater_than(0) }
    it { is_expected.to validate_presence_of(:used_bytes) }
    it { is_expected.to validate_numericality_of(:used_bytes).is_greater_than_or_equal_to(0) }
    it { is_expected.to validate_presence_of(:tier) }
    it { is_expected.to validate_inclusion_of(:tier).in_array(described_class::TIERS) }
  end

  describe '#usage_percentage' do
    it 'calculates correct percentage' do
      quota = build(:storage_quota, quota_bytes: 100, used_bytes: 25)
      expect(quota.usage_percentage).to eq(25.0)
    end

    it 'returns 0 when nothing is used' do
      quota = build(:storage_quota, quota_bytes: 1, used_bytes: 0)
      expect(quota.usage_percentage).to eq(0.0)
    end

    it 'returns 0 instead of dividing by zero when quota is zero' do
      quota = build(:storage_quota, quota_bytes: 0, used_bytes: 10)
      expect(quota.usage_percentage).to eq(0)
    end
  end

  describe '#over_quota?' do
    it 'returns true when over quota' do
      quota = build(:storage_quota, :over_quota)
      expect(quota).to be_over_quota
    end

    it 'returns false when under quota' do
      quota = build(:storage_quota)
      expect(quota).not_to be_over_quota
    end
  end

  describe '#remaining_bytes' do
    it 'returns remaining bytes' do
      quota = build(:storage_quota, quota_bytes: 100, used_bytes: 30)
      expect(quota.remaining_bytes).to eq(70)
    end

    it 'returns 0 when over quota' do
      quota = build(:storage_quota, :over_quota)
      expect(quota.remaining_bytes).to eq(0)
    end
  end

  describe 'scopes' do
    let!(:normal_quota) { create(:storage_quota) }
    let!(:over_quota) { create(:storage_quota, :over_quota) }

    describe '.over_quota' do
      it 'returns quotas that are over limit' do
        expect(described_class.over_quota).to include(over_quota)
        expect(described_class.over_quota).not_to include(normal_quota)
      end
    end
  end
end
