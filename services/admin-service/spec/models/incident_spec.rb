require 'rails_helper'

RSpec.describe Incident do
  include ActiveSupport::Testing::TimeHelpers

  describe 'validations' do
    it { is_expected.to validate_presence_of(:title) }
    it { is_expected.to validate_length_of(:title).is_at_most(255) }
    it { is_expected.to validate_presence_of(:description) }
    it { is_expected.to validate_presence_of(:severity) }
    it { is_expected.to validate_inclusion_of(:severity).in_array(described_class::SEVERITIES) }
    it { is_expected.to validate_presence_of(:status) }
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

  describe 'scopes' do
    let!(:open_incident) { create(:incident, severity: 'high') }
    let!(:investigating) { create(:incident, :investigating, severity: 'low') }
    let!(:resolved) { create(:incident, :resolved, severity: 'high') }

    it '.active returns open and investigating incidents' do
      expect(described_class.active).to contain_exactly(open_incident, investigating)
    end

    it '.by_status filters by status' do
      expect(described_class.by_status('resolved')).to contain_exactly(resolved)
    end

    it '.by_severity filters by severity' do
      expect(described_class.by_severity('high')).to contain_exactly(open_incident, resolved)
    end
  end

  describe '#can_transition_to?' do
    {
      'open' => { allowed: %w[investigating resolved], denied: %w[open closed] },
      'investigating' => { allowed: %w[resolved], denied: %w[open investigating closed] },
      'resolved' => { allowed: %w[closed], denied: %w[open investigating resolved] },
      'closed' => { allowed: [], denied: %w[open investigating resolved closed] }
    }.each do |from, rules|
      context "when status is #{from}" do
        subject(:incident) { build(:incident, status: from) }

        rules[:allowed].each do |to|
          it("allows #{to}") { expect(incident.can_transition_to?(to)).to be(true) }
        end

        rules[:denied].each do |to|
          it("denies #{to}") { expect(incident.can_transition_to?(to)).to be(false) }
        end
      end
    end
  end

  describe 'transitions' do
    it '#investigate! moves an open incident to investigating' do
      incident = create(:incident)
      incident.investigate!
      expect(incident.reload.status).to eq('investigating')
    end

    it '#resolve! sets status and resolved_at' do
      incident = create(:incident, :investigating)
      freeze_time do
        incident.resolve!
        expect(incident.reload.status).to eq('resolved')
        expect(incident.resolved_at).to eq(Time.current)
      end
    end

    it '#close! sets status and closed_at' do
      incident = create(:incident, :resolved)
      freeze_time do
        incident.close!
        expect(incident.reload.status).to eq('closed')
        expect(incident.closed_at).to eq(Time.current)
      end
    end

    it 'raises InvalidTransitionError and does not persist an invalid transition' do
      incident = create(:incident, :closed)
      expect { incident.investigate! }
        .to raise_error(Incident::InvalidTransitionError, "Cannot transition from 'closed' to 'investigating'")
      expect(incident.reload.status).to eq('closed')
    end

    it 'does not allow closing an open incident directly' do
      incident = create(:incident)
      expect { incident.close! }.to raise_error(Incident::InvalidTransitionError)
      expect(incident.reload.closed_at).to be_nil
    end
  end

  describe 'predicates' do
    it '#active? is true only for open and investigating' do
      expect(build(:incident).active?).to be(true)
      expect(build(:incident, :investigating).active?).to be(true)
      expect(build(:incident, :resolved).active?).to be(false)
      expect(build(:incident, :closed).active?).to be(false)
    end

    it '#has_devin_session? reflects devin_session_id presence' do
      expect(build(:incident).has_devin_session?).to be(false)
      expect(build(:incident, devin_session_id: 'abc').has_devin_session?).to be(true)
    end

    it '#has_active_devin_session? requires a running session' do
      expect(build(:incident, devin_session_id: 'abc', devin_session_status: 'running')
               .has_active_devin_session?).to be(true)
      expect(build(:incident, devin_session_id: 'abc', devin_session_status: 'finished')
               .has_active_devin_session?).to be(false)
      expect(build(:incident, devin_session_status: 'running').has_active_devin_session?).to be(false)
    end
  end
end
