import src.user_interaction as usr_int
import src.file_handler as file_handler

class AbstractNode:
    """
    Every child of abstractnode has to define process and initialize_node.
    Its suggested to replace reinitialize_node
    Its only necessary to replace plot_output if you allow users to retry
    """
    def __init__(self,
                 output_name="",
                 requirements=[],
                 user_can_retry=False,
                 node_title="Uninitialized Node Title"):
        self.requirement_exists = {}
        self.output_name = output_name
        self.requirements = requirements
        self.user_can_retry = user_can_retry
        self.node_title = node_title
        self.requirements_met = True
        

    def get_output_name(self):
        return self.output_name

    def process(self):
        print("This is the default process method that does nothing")
        return None

    def initialize_node(self):
        print("This is the default initialization method that does nothing")

    def reinitialize_node(self):
        self.initialize_node()

    def plot_output(self):
        print("This is the default plot method that does nothing")

    def ask_user_if_they_have_substitute_for_requirement(self, requirement):
        prompt = "The requirement {requirement} has not been met by a"
        prompt += "step earlier in the pipeline. Do you have a replacement?"
        

    def check_requirements(self):
        from src.fishnet import FishNet
        for requirement in self.requirements:
            if requirement not in FishNet.pipeline_output.keys():
                user_response_id = usr_int.ask_if_user_has_replacement_for_requirement(requirement)
                if user_response_id == usr_int.positive_response_id:
                    loaded_img = file_handler.load_img_file()
                    FishNet.pipeline_output[requirement] = loaded_img
                elif user_response_id == usr_int.negative_response_id:
                    self.requirements_met = False

    def node_intro_msg(self):
        prompt = f"\n---- Commencing {self.node_title} ----\n"
        print(prompt)

    def run(self):
        self.node_intro_msg()
        self.check_requirements()
        if self.requirements_met is False:
            return None

        self.initialize_node()
        if self.user_can_retry:
            usr_feedback = usr_int.retry_response_id
            first_pass = True
            while usr_feedback == usr_int.retry_response_id:
                if not first_pass:
                    self.reinitialize_node()

                node_output = self.process()
                self.plot_output()
                usr_feedback = usr_int.get_user_feedback_for_node_output()
                # Close output maybe?

                if usr_feedback == usr_int.satisfied_response_id:
                    return node_output
                elif usr_feedback == usr_int.quit_response_id:
                    return None
                if first_pass:
                    first_pass = False
        else:
            node_output = self.process()
            return node_output
