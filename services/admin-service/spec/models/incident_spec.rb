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
    let!(:open_incident) { create(:incident) }
    let!(:investigating) { create(:incident, :investigating) }
    let!(:resolved) { create(:incident, :resolved) }

    it 'returns only open and investigating incidents' do
      expect(described_class.active).to contain_exactly(open_incident, investigating)
    end
  end

  describe '#can_transition_to?' do
    it 'follows VALID_TRANSITIONS' do
      expect(build(:incident).can_transition_to?('investigating')).to be(true)
      expect(build(:incident).can_transition_to?('resolved')).to be(true)
      expect(build(:incident).can_transition_to?('closed')).to be(false)
      expect(build(:incident, :investigating).can_transition_to?('open')).to be(false)
      expect(build(:incident, :resolved).can_transition_to?('closed')).to be(true)
      expect(build(:incident, :closed).can_transition_to?('open')).to be(false)
    end
  end

  describe '#investigate!' do
    it 'moves an open incident to investigating' do
      incident = create(:incident)
      incident.investigate!
      expect(incident.reload.status).to eq('investigating')
    end
  end

  describe '#resolve!' do
    it 'moves an investigating incident to resolved and stamps resolved_at' do
      incident = create(:incident, :investigating)
      incident.resolve!
      incident.reload
      expect(incident.status).to eq('resolved')
      expect(incident.resolved_at).to be_present
    end

    it 'resolves an open incident directly' do
      incident = create(:incident)
      incident.resolve!
      incident.reload
      expect(incident.status).to eq('resolved')
      expect(incident.resolved_at).to be_present
    end
  end

  describe '#close!' do
    it 'moves a resolved incident to closed and stamps closed_at' do
      incident = create(:incident, :resolved)
      incident.close!
      incident.reload
      expect(incident.status).to eq('closed')
      expect(incident.closed_at).to be_present
    end

    it 'raises and leaves the record unchanged for an invalid transition' do
      incident = create(:incident)
      expect { incident.close! }.to raise_error(Incident::InvalidTransitionError, /from 'open' to 'closed'/)
      expect(incident.reload.status).to eq('open')
      expect(incident.closed_at).to be_nil
    end
  end

  describe '#active?' do
    it 'is true for open and investigating, false otherwise' do
      expect(build(:incident)).to be_active
      expect(build(:incident, :investigating)).to be_active
      expect(build(:incident, :resolved)).not_to be_active
    end
  end

  describe 'Devin session helpers' do
    it 'reports whether a session is attached and running' do
      expect(build(:incident)).not_to have_devin_session
      expect(build(:incident, devin_session_id: 'abc', devin_session_status: 'running')).to have_active_devin_session
      expect(build(:incident, devin_session_id: 'abc', devin_session_status: 'finished'))
        .not_to have_active_devin_session
    end
  end
end
