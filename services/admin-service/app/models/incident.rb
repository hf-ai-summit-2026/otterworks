class Incident < ApplicationRecord
  SEVERITIES = %w[low medium high critical].freeze
  STATUSES = %w[open investigating resolved closed].freeze
  AFFECTED_SERVICES = %w[
    api-gateway auth-service file-service document-service
    collab-service notification-service search-service
    analytics-service admin-service audit-service report-service
  ].freeze

  VALID_TRANSITIONS = {
    'open' => %w[investigating resolved],
    'investigating' => %w[resolved],
    'resolved' => %w[closed],
    'closed' => %w[]
  }.freeze

  validates :title, presence: true, length: { maximum: 255 }
  validates :description, presence: true
  validates :severity, presence: true, inclusion: { in: SEVERITIES }
  validates :status, presence: true, inclusion: { in: STATUSES }
  validates :affected_service, inclusion: { in: AFFECTED_SERVICES }, allow_blank: true

  scope :by_status, ->(status) { where(status: status) }
  scope :by_severity, ->(severity) { where(severity: severity) }
  scope :active, -> { where(status: %w[open investigating]) }

  def investigate!
    transition_to!('investigating')
  end

  def resolve!
    transition_to!('resolved', resolved_at: Time.current)
  end

  def close!
    transition_to!('closed', closed_at: Time.current)
  end

  def can_transition_to?(new_status)
    VALID_TRANSITIONS.fetch(status, []).include?(new_status)
  end

  def active?
    %w[open investigating].include?(status)
  end

  def self.devin_session_attributes(session_result)
    {
      devin_session_id: session_result[:session_id],
      devin_session_url: session_result[:url],
      devin_session_status: 'running'
    }
  end

  def sync_devin_session(session_info)
    update(
      devin_session_status: session_info[:status],
      devin_session_url: session_info[:url] || devin_session_url
    )
  end

  # rubocop:disable Naming/PredicatePrefix -- public method names used by controllers
  def has_devin_session?
    devin_session_id.present?
  end

  def has_active_devin_session?
    devin_session_id.present? && devin_session_status == 'running'
  end
  # rubocop:enable Naming/PredicatePrefix

  private

  def transition_to!(new_status, extras = {})
    unless can_transition_to?(new_status)
      raise InvalidTransitionError, "Cannot transition from '#{status}' to '#{new_status}'"
    end

    update!(extras.merge(status: new_status))
  end

  class InvalidTransitionError < StandardError; end
end
