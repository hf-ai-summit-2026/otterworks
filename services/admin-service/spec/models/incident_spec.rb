require 'rails_helper'

RSpec.describe Incident do
  describe 'validations' do
    it { is_expected.to validate_presence_of(:title) }
    it { is_expected.to validate_length_of(:title).is_at_most(255) }
    it { is_expected.to validate_presence_of(:description) }
    it { is_expected.to validate_inclusion_of(:severity).in_array(described_class::SEVERITIES) }
    it { is_expected.to validate_inclusion_of(:status).in_array(described_class::STATUSES) }

    it 'allows a blank affected_service' do
      expect(build(:incident, affected_service: nil)).to be_valid
    end

    it 'rejects an unknown affected_service' do
      incident = build(:incident, affected_service: 'not-a-service')
      expect(incident).not_to be_valid
      expect(incident.errors[:affected_service]).to be_present
    end
  end

  describe '.active' do
    it 'returns only open and investigating incidents' do
      open = create(:incident)
      investigating = create(:incident, :investigating)
      resolved = create(:incident, :resolved)
      closed = create(:incident, :closed)

      expect(described_class.active).to include(open, investigating)
      expect(described_class.active).not_to include(resolved, closed)
    end
  end

  describe '#can_transition_to?' do
    it 'follows VALID_TRANSITIONS' do
      expect(build(:incident).can_transition_to?('investigating')).to be true
      expect(build(:incident).can_transition_to?('resolved')).to be true
      expect(build(:incident).can_transition_to?('closed')).to be false
      expect(build(:incident, :investigating).can_transition_to?('open')).to be false
      expect(build(:incident, :resolved).can_transition_to?('closed')).to be true
      expect(build(:incident, :closed).can_transition_to?('open')).to be false
    end
  end

  describe '#investigate!' do
    it 'moves an open incident to investigating' do
      incident = create(:incident)
      incident.investigate!
      expect(incident.reload.status).to eq('investigating')
    end

    it 'raises for a resolved incident' do
      incident = create(:incident, :resolved)
      expect { incident.investigate! }.to raise_error(described_class::InvalidTransitionError)
      expect(incident.reload.status).to eq('resolved')
    end
  end

  describe '#resolve!' do
    it 'resolves and stamps resolved_at' do
      incident = create(:incident, :investigating)
      incident.resolve!
      expect(incident.reload.status).to eq('resolved')
      expect(incident.resolved_at).to be_present
    end
  end

  describe '#close!' do
    it 'closes a resolved incident and stamps closed_at' do
      incident = create(:incident, :resolved)
      incident.close!
      expect(incident.reload.status).to eq('closed')
      expect(incident.closed_at).to be_present
    end

    it 'raises for an open incident' do
      incident = create(:incident)
      expect { incident.close! }.to raise_error(described_class::InvalidTransitionError, /from 'open' to 'closed'/)
    end
  end

  describe 'devin session helpers' do
    it 'reports session presence and activity' do
      expect(build(:incident)).not_to have_devin_session
      expect(build(:incident, devin_session_id: 'abc', devin_session_status: 'running')).to have_active_devin_session
      expect(build(:incident, devin_session_id: 'abc', devin_session_status: 'finished')).not_to have_active_devin_session
    end
  end
end
