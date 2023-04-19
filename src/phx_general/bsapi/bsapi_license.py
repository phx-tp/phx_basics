import time

from phx_general.file import file2list


class BSAPILicense:

    class Technology:

        def __init__(self):
            self.name = ""
            self.slots = 0
            self.until = ""

    def __init__(self, bsapi_license_file):
        self.technologies = dict()
        self.parse(bsapi_license_file)

    def parse(self, bsapi_license_file):
        lines = file2list(bsapi_license_file)
        for l in lines:
            if not l.startswith('PRODUCT'):
                continue

            _, name, _, _, _, _, _, _, slots, until_y, until_h = l.strip().split()
            t = BSAPILicense.Technology()
            t.name = name
            t.slots = int(slots.replace('slots:', ''))
            t.until = time.strptime(f"{until_y.replace('until:', '')} {until_h}", "%Y-%m-%d %H:%M:%S")
            self.technologies[name] = t

    def get_number_of_slots(self, technology_name):
        if technology_name not in self.technologies:
            raise ValueError(f"Technology with name '{technology_name}' not present in license file! - "
                             " present technologies: {self.technologies.keys()}")

        tech = self.technologies[technology_name]
        if time.gmtime() > tech.until:
            raise ValueError(f"License for technology with name '{technology_name}' is valid only until {tech.until}!")

        return tech.slots
